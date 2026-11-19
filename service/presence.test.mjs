import assert from "node:assert/strict";
import {test} from "node:test";
import {readFileSync} from "node:fs";
import {DatabaseSync} from "node:sqlite";
import worker from "../public/_worker.js";

function database() {
    const db = new DatabaseSync(":memory:");
    db.exec(readFileSync(new URL("./presence.sql",import.meta.url),"utf8"));
    const prepared = (sql,params) => ({
        bind: (...values) => prepared(sql,values),
        first: () => db.prepare(sql).get(...params) || null,
        all: () => ({results: db.prepare(sql).all(...params)}),
        run: () => db.prepare(sql).run(...params)
    });
    return {db, env:{PRESENCE:{prepare:sql=>prepared(sql,[]),batch:items=>items.map(x=>x.run())}}};
}

test("authenticated, opt-in roster, unique machines, expiry, pagination and logout", async t => {
    const {db,env} = database();
    t.after(()=>db.close());
    const users = new Map([["a".repeat(16),"Ada"],["b".repeat(16),"Ben"],["c".repeat(16),"Ada"]]);
    let upstreamStatus = 200;
    t.mock.method(globalThis, "fetch", async (url, options) => {
        assert.equal(url,"https://havoc-keys.ninjabro0329.workers.dev/verify-check");
        assert.equal(options.redirect,"manual");
        if (upstreamStatus !== 200) return new Response("",{status:upstreamStatus,headers:{"Location":"https://redirect.invalid/"}});
        const body = JSON.parse(options.body);
        assert.equal(body.hwid,body.hwidLegacy);
        const label = users.get(body.hwid);
        return Response.json(label ? {ok:true,label} : {ok:false});
    });
    async function api(method,route,token,body,extra={}) {
        const headers = {"Content-Type":"application/json",...extra};
        if (token) headers.Authorization = "Bearer " + token;
        const r = await worker.fetch(new Request("https://app.test/api/presence/"+route,
            {method, headers, body:body === undefined ? undefined : JSON.stringify(body)}),env);
        assert.equal(r.headers.get("cache-control"),"private, no-store");
        return [r.status,await r.json()];
    }
    const total = async token => (await api("GET","count",token))[1];
    assert.equal((await api("GET","count"))[0],401);
    const make = (id,legacy=id) => api("POST","session",null,{hwid:id,hwidLegacy:legacy,name:"Impersonator"});
    const visible = (token,on) => api("PUT","live",token,{visible:on});
    assert.equal((await api("GET","members"))[0],401);
    assert.equal((await make("junk"))[0],400);
    assert.equal((await make("f".repeat(16)))[0],403);
    assert.equal((await api("POST","session",null,{}, {Origin:"https://wrong.test"}))[0],403);
    assert.equal((await api("POST","session",null,{x:"a".repeat(700)}))[0],400);
    const [code,{token:a}] = await make("a".repeat(16));
    const [, {token:a2}] = await make("a".repeat(16));
    const [, {token:b}] = await make("f".repeat(16),"b".repeat(16));
    const [, {token:c}] = await make("c".repeat(16));
    assert.equal(code,201);
    assert.deepEqual((await api("GET","members",a))[1],{members:[],next:null});
    assert.equal((await visible(a,"true"))[0],400);
    const cutoff = Math.floor(Date.now()/1000) + 45;
    assert.equal((await api("PUT","live",a,{visible:true,until:"tomorrow"}))[0],400);
    assert.equal((await api("PUT","live",a,{visible:true,until:cutoff}))[0],200);
    assert.equal(db.prepare("SELECT MAX(visible_until) AS n FROM presence_session").get().n,cutoff);
    assert.deepEqual(await total(a),{count:1});
    assert.equal((await api("PUT","live",a,{visible:true,until:cutoff-60}))[0],200);
    assert.deepEqual(await total(a),{count:0});
    for (const token of [a,a2,b,c]) assert.equal((await visible(token,true))[0],200);
    assert.deepEqual(await total(a),{count:3});
    const roster = (await api("GET","members",a))[1];
    assert.deepEqual(roster.members.map(x=>x.name).sort(),["Ada","Ada","Ben"]);
    assert.deepEqual(Object.keys(roster.members[0]).sort(),["id","name"]);
    const stored = JSON.stringify(db.prepare("SELECT * FROM presence_session").all());
    for (const value of [a,b,"a".repeat(16),"b".repeat(16)]) assert.ok(!stored.includes(value));
    await visible(b,false);
    assert.deepEqual(await total(b),{count:2});
    assert.equal((await api("GET","members",b))[1].members.length,2);
    await api("DELETE","session",a);
    assert.equal((await api("GET","members",a))[0],401);
    db.exec("UPDATE presence_session SET visible_until=1");
    assert.equal((await api("GET","members",b))[1].members.length,0);
    assert.deepEqual(await total(b),{count:0});
    const insert = db.prepare("INSERT INTO presence_session VALUES(?,?,?,?,?)");
    for(let i=0;i<206;i++) {
        const id=i.toString(16).padStart(24,"0");
        insert.run(id+"d".repeat(40),"member"+i,"Person "+i,9999999999,9999999999);
    }
    assert.deepEqual(await total(b),{count:206});
    let route="members", rows=[];
    do {
        const [status,page] = await api("GET",route,b);
        assert.equal(status,200);
        rows.push(...page.members);
        route=page.next ? "members?after="+page.next : null;
    } while (route);
    assert.equal(new Set(rows.map(x=>x.id)).size,206);
    assert.equal((await api("GET","members?after=broken",b))[0],400);
    db.exec("UPDATE presence_session SET expires=1");
    assert.equal((await api("GET","members",b))[0],401);
    await make("a".repeat(16));
    assert.equal(db.prepare("SELECT count(*) AS n FROM presence_session").get().n,1);
    for (upstreamStatus of [302,502]) assert.equal((await make("a".repeat(16)))[0],503);
});

test("unconfigured service and unrelated static assets", async () => {
    const absent = await worker.fetch(new Request("https://app.test/api/presence/members"),{});
    assert.equal(absent.status,503);
    const asset = await worker.fetch(new Request("https://app.test/desktop/stable.json"), {ASSETS:{fetch:()=>new Response("asset")}});
    assert.equal(await asset.text(),"asset");
});

test("old and new desktops receive compatible scheduled messages", async t => {
    const start = Date.UTC(2026,10,19,14);
    const end = start + 60000;
    const feed = {message:"Default",schedule:[{start:new Date(start).toISOString(),
        end:new Date(end).toISOString(),message:"Scheduled"}]};
    const env = {ASSETS:{fetch:()=>Response.json(feed)}};
    const url = "https://app.test/desktop/daily-message.json";
    const clock = t.mock.method(Date,"now",()=>start);
    for (const [now,message] of [[start-1,"Default"],[start,"Scheduled"],[end-1,"Scheduled"],[end,"Default"]]) {
        clock.mock.mockImplementation(()=>now);
        const r = await worker.fetch(new Request(url),env);
        assert.deepEqual(await r.json(),{message});
    }
    const full = await worker.fetch(new Request(url+"?schedule=1"),env);
    assert.deepEqual(await full.json(),feed);
    const head = await worker.fetch(new Request(url,{method:"HEAD"}),env);
    assert.equal(await head.text(),"");
    assert.equal(head.status,200);
});
