const root = "/api/presence/";
const verification = "https://havoc-keys.ninjabro0329.workers.dev/verify-check";
const heartbeatTTL = 100;
const sessionTTL = 900;
const pageSize = 100;
const encode = new TextEncoder();
const hex = bytes => Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, "0")).join("");
const randomToken = () => hex(crypto.getRandomValues(new Uint8Array(32)));
const digest = async value => hex(await crypto.subtle.digest("SHA-256", encode.encode(value)));

function json(status, data) {
    return Response.json(data, {status, headers: {"Cache-Control":"private, no-store", "X-Content-Type-Options":"nosniff"}});
}

async function readJSON(message, limit) {
    if (!message.body || Number(message.headers.get("content-length")) > limit) throw new Error("size");
    const reader = message.body.getReader();
    const chunks = [];
    let size = 0;
    for (;;) {
        const {value, done} = await reader.read();
        if (done) break;
        size += value.length;
        if (size > limit) {
            await reader.cancel();
            throw new Error("size");
        }
        chunks.push(value);
    }
    return JSON.parse(await new Blob(chunks).text());
}

async function verifiedLabel(id) {
    const response = await fetch(verification, {
        method:"POST", redirect:"manual", signal:AbortSignal.timeout(9000),
        headers:{"Content-Type":"application/json","Accept":"application/json"},
        body:JSON.stringify({hwid:id, hwidLegacy:id})
    });
    if ([401,403].includes(response.status)) { await response.body?.cancel(); return null; }
    if (!response.ok) { await response.body?.cancel(); throw new Error("auth service unavailable"); }
    const data = await readJSON(response, 8 * 1024 * 1024);
    if (data?.ok !== true) return null;
    const label = typeof data.label === "string" ? data.label.replace(/[\p{C}]/gu,"").trim().replace(/\s+/gu," ").slice(0,80) : "";
    return label || "Verified user";
}

async function openSession(db, body, now) {
    const ids = [...new Set([body?.hwid, body?.hwidLegacy])];
    if (!ids.every(id => typeof id === "string" && /^[0-9a-f]{16}$/.test(id)))
        return json(400,{error:"Invalid verification details"});
    for (const id of ids) {
        const label = await verifiedLabel(id);
        if (!label) continue;
        // Key the short-lived member ID on the server. A machine identifier is never written to D1.
        let meta = await db.prepare("SELECT pepper FROM presence_meta WHERE id=1").first();
        if (!meta) {
            await db.prepare("INSERT OR IGNORE INTO presence_meta VALUES (1,?)").bind(randomToken()).run();
            meta = await db.prepare("SELECT pepper FROM presence_meta WHERE id=1").first();
        }
        const key = await crypto.subtle.importKey("raw", encode.encode(meta.pepper), {name:"HMAC",hash:"SHA-256"}, false, ["sign"]);
        const member = hex(await crypto.subtle.sign("HMAC", key, encode.encode(id)));
        const token = randomToken();
        await db.batch([
            db.prepare("DELETE FROM presence_session WHERE expires <= ?").bind(now),
            db.prepare("INSERT INTO presence_session(token_hash,member,label,expires) VALUES(?,?,?,?)")
              .bind(await digest(token), member, label, now + sessionTTL)
        ]);
        return json(201,{token});
    }
    return json(403,{error:"Verification required"});
}

export default {
    async fetch(request, env) {
        const url = new URL(request.url);
        if (!url.pathname.startsWith(root)) return env.ASSETS.fetch(request);
        const route = url.pathname.slice(root.length);
        if (!["session","live","members"].includes(route)) return json(404,{error:"Unknown endpoint"});
        const allowed = {session:["POST","DELETE"],live:["PUT"],members:["GET"]}[route];
        if (!allowed.includes(request.method)) return json(405,{error:"Method unavailable"});
        const origin = request.headers.get("Origin");
        if (origin && origin !== url.origin) return json(403,{error:"Origin rejected"});
        if (!env.PRESENCE) return json(503,{error:"Online list unavailable"});
        const db = env.PRESENCE;
        const now = Math.floor(Date.now()/1000);
        try {
            const creating = route === "session" && request.method === "POST";
            let hash;
            if (!creating) {
                const match = /^Bearer ([0-9a-f]{64})$/.exec(request.headers.get("Authorization") || "");
                if (!match) return json(401,{error:"Session required"});
                hash = await digest(match[1]);
                const session = await db.prepare("SELECT 1 AS valid FROM presence_session WHERE token_hash=? AND expires>?").bind(hash,now).first();
                if (!session) return json(401,{error:"Session expired"});
            }
            if (creating || route === "live") {
                if (!request.headers.get("Content-Type")?.startsWith("application/json")) return json(415,{error:"JSON required"});
                let body;
                try { body = await readJSON(request,512); } catch { return json(400,{error:"Invalid request"}); }
                if (creating) return await openSession(db,body,now);
                if (typeof body?.visible !== "boolean") return json(400,{error:"Visibility must be a boolean"});
                await db.prepare("UPDATE presence_session SET visible_until=MIN(?,expires) WHERE token_hash=? AND expires>?")
                        .bind(body.visible ? now+heartbeatTTL : 0,hash,now).run();
                return json(200,{ok:true});
            }
            if (route === "session") {
                await db.prepare("DELETE FROM presence_session WHERE token_hash=?").bind(hash).run();
                return json(200,{ok:true});
            }
            const after = url.searchParams.get("after") || "";
            if (after && !/^[0-9a-f]{24}$/.test(after)) return json(400,{error:"Invalid cursor"});
            // A roster ID is temporary and does not reveal a machine, a session token or a stable member ID.
            const {results} = await db.prepare(`SELECT MIN(substr(token_hash,1,24)) AS id, MAX(label) AS name
                FROM presence_session WHERE visible_until>? AND expires>? GROUP BY member
                HAVING MIN(substr(token_hash,1,24))>? ORDER BY id LIMIT ?`).bind(now,now,after,pageSize+1).all();
            const members = results.slice(0,pageSize);
            return json(200,{members,next:results.length>pageSize ? members.at(-1).id : null});
        } catch {
            return json(503,{error:"Online list temporarily unavailable"});
        }
    }
};
