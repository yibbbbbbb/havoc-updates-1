# Havoc Midnight desktop

[Download HavocMidnight.py](https://havoc-midnight-preview.pages.dev/desktop/HavocMidnight.py) · [Release notes](https://havoc-midnight-preview.pages.dev/)

Save the Python file in a writable folder. On Windows, install the UI library with `py -m pip install imgui-bundle` and run `py HavocMidnight.py`. On macOS and Linux, use `python3 -m pip install imgui-bundle pygame` and `python3 HavocMidnight.py`. Use Python 3.10 or later. The desktop keeps its settings, presets, artwork and sounds in the current user's Havoc data folder.

## Using the desktop

Open **Home → Updates** or **Sign in → Release notes** and select **Check for updates**. When a newer release is available, **Install … and restart** downloads it, verifies it and restarts Havoc. Turn on **Check for updates on startup** to see a notice when a release is available. Installation always takes a click. The updater keeps the preceding file beside the desktop as `HavocMidnight.py.previous`. **Restore previous version and restart** checks that backup against the history of published releases before restoring it. Your workspace and preferences are stored separately.

In Midnight, open **Library** and choose a collection, then a page. Wide windows show collection tabs and a page list. Compact windows use two selectors. On a control page, **All**, **Enabled** and **Changed** work alongside search. **Changed** includes edited options whose parent is off. Expand a mod’s summary to edit its options. Use **Reset** on an individual setting to restore its original value. Choosing a control in the command palette opens its group and highlights the exact row.

On **Appearance**, the live sample stays above the scrolling settings. Try its button, toggle and slider in either layout. Smaller windows collapse the sample under **Live preview**.

**Connection** shows the current headset state and the next step first. From there, expand **Connection diagnostics** and choose **Copy report**. The report includes the ADB state, device count, authorization state and suggested next step. It omits device names, addresses, account identifiers and raw error text.

In **Presets** or **Appearance**, choose a preset and select **Preview** to review each change. **Apply preset** saves it. **Undo preset** reverses the last application in that category for the current session.

The green dot in the bottom-left status bar shows how many verified users are sharing their presence. It refreshes every 30 seconds. A gray dot and a dash mean a current count is unavailable. Select the count or open **Home → Who's online** to view the names shared by verified Havoc desktop users. **Show me online** starts sharing your verified display name. Visibility starts off. Choose **For one hour**, **Until I quit**, or **Until I turn it off**. The service enforces the one-hour deadline even if the desktop stops responding. An explicit logout clears the saved choice. Normal exits send a best-effort sign-out. An interrupted connection expires after at most 100 seconds. If the service is unreachable, the desktop retries automatically. Select **Retry connection** in the online list to try immediately.

[Online list with two local test accounts](previews/online-test-accounts.png) · [Update offered to an older desktop copy](previews/desktop-update.png)

## Daily message

Both desktop layouts show the same public message before and after sign-in. From the release repository, the publisher can run `python service/announcements.py` with Tk installed. Enter a default message or give a draft a UTC start and expiry. Use **Preview Midnight** or **Preview Classic** to see the draft in the desktop. Choose **Queue / replace**, then **Save schedule**. Commit `public/desktop/daily-message.json` and deploy the Pages site to publish it.

Messages allow 1–120 printable characters. Up to 64 nonoverlapping intervals can be queued. The default appears between intervals. Desktops refresh the schedule within 15 minutes and at midnight UTC. A cached schedule also switches at its boundaries offline. Older desktops receive the currently active message on their normal refresh.

## Publishing a desktop release

1. Advance the three-part `DESKTOP_RELEASE` in the maintained desktop source, build it and test it. The desktop builder includes the SHA-256 and version of each earlier stable release in `TRUSTED_BACKUPS`. If editing the standalone source directly, retain that history and add the preceding stable manifest’s digest and version. Commit the finished standalone file at `public/desktop/HavocMidnight.py` to this repository.
2. From this checkout, run `python service/publish_manifest.py <full-artifact-commit-id>`. It checks the committed bytes against the local file and writes `public/desktop/stable.json`. Commit that file to `main`.
3. Deploy the contents of `public/` to the existing Cloudflare Pages project **havoc-midnight-preview**. Include the Pages advanced-mode Worker, routes and headers. The desktop trusts the production hostname, so deployments to a preview alias do not promote a release.
4. Check the update button from an older copy. The installed version, SHA-256 digest, byte size and immutable Git revision must agree across the two release channels before installation. Keep the GitHub repository and Cloudflare production deployment restricted to trusted publishers.

## Online service

The production Pages Worker serves `/api/presence/*` using the `PRESENCE` binding to `havoc-midnight-presence`. For an approved deployment, apply `service/presence.sql` to the presence database, bind it as `PRESENCE` in the Pages production settings and redeploy. The API returns HTTP 503 while the binding is absent.

The Worker verifies the same machine identity used for Havoc sign-in. It never stores raw machine IDs or IP addresses in the presence database. It keeps a keyed member identifier to count multiple desktop windows once, a hash of the temporary bearer token, the verified display name and expiration times. The roster exposes only display names and temporary row IDs to verified clients. Sessions expire after 15 minutes, expired rows are discarded on the next verified session creation, and logout deletes that session. Machine verification data and bearer tokens belong exclusively in HTTPS request bodies or headers.

Run `python -m unittest discover -s tests` in the desktop Python environment for updater and presence-client tests. Run `node --test service/presence.test.mjs` with Node 24 or later for the service tests. To preview the static pages locally, run `python -m http.server 8080 --directory public` and open <http://localhost:8080>.

## Discord release announcements

The **Havoc release announcements** workflow watches stable promotions on `main`. It waits for GitHub and Cloudflare to serve matching manifests, verifies the public desktop download, and uses the changelog from that exact file. The announcement includes the version, update instructions, and download link. Configure the channel’s incoming webhook as the repository Actions secret `DISCORD_WEBHOOK_URL`.

Open **Actions → Havoc release announcements → Run workflow** for a read-only preview. Leave **Post the current live release to Discord** unchecked. Previews verify the live Discord connection without posting. Changes to the announcement workflow and its script also run a preview when the stable manifest is unchanged.

Each delivery reserves a Git tag, `discord-announcement/<version>`, before posting. Reruns skip versions with an existing tag. If Discord reports an error after the tag was reserved, check the channel first. If the announcement is missing, delete that version’s reservation tag and run the workflow with publishing selected. A superseded release is skipped.
