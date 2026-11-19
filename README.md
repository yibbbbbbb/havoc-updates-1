# Havoc Midnight desktop

[Download HavocMidnight.py](https://havoc-midnight-preview.pages.dev/desktop/HavocMidnight.py) · [Release notes](https://havoc-midnight-preview.pages.dev/)

Save the Python file in a writable folder. On Windows, install the UI library with `py -m pip install imgui-bundle` and run `py HavocMidnight.py`. On macOS and Linux, use `python3 -m pip install imgui-bundle pygame` and `python3 HavocMidnight.py`. Use Python 3.10 or later. The desktop keeps its settings, presets, artwork and sounds in the current user's Havoc data folder.

## Using the desktop

Open **Home → Updates** or **Sign in → Release notes** and select **Check for updates**. When a newer release is available, **Install … and restart** downloads it, verifies it and restarts Havoc. The preceding file is saved beside the desktop as `HavocMidnight.py.previous`.

Open **Home → Who's online** to view the names shared by verified Havoc desktop users. **Show me online** starts sharing your verified display name. Visibility starts off. An explicit logout clears the saved choice. Normal exits send a best-effort sign-out. An interrupted connection expires after at most 100 seconds. An unreachable service shows a retry message.

[Online list with two local test accounts](previews/online-test-accounts.png) · [Update offered to an older desktop copy](previews/desktop-update.png)

## Publishing a desktop release

1. Advance the three-part `DESKTOP_RELEASE` in the maintained desktop source, build it and test it. Commit the finished standalone file at `public/desktop/HavocMidnight.py` to this repository.
2. From this checkout, run `python service/publish_manifest.py <full-artifact-commit-id>`. It checks the committed bytes against the local file and writes `public/desktop/stable.json`. Commit that file to `main`.
3. Deploy the contents of `public/` to the existing Cloudflare Pages project **havoc-midnight-preview**. Include the Pages advanced-mode Worker, routes and headers. The desktop trusts the production hostname, so deployments to a preview alias do not promote a release.
4. Check the update button from an older copy. The installed version, SHA-256 digest, byte size and immutable Git revision must agree across the two release channels before installation. Keep the GitHub repository and Cloudflare production deployment restricted to trusted publishers.

## Online service

The Pages Worker serves `/api/presence/*`. It uses the `PRESENCE` D1 binding. For an approved deployment, apply `service/presence.sql` to the presence database, bind it as `PRESENCE` in the Pages production settings and redeploy. The API returns HTTP 503 while the binding is absent.

The Worker verifies the same machine identity used for Havoc sign-in. It never stores raw machine IDs or IP addresses in the presence database. It keeps a keyed member identifier to count multiple desktop windows once, a hash of the temporary bearer token, the verified display name and expiration times. The roster exposes only display names and temporary row IDs to verified clients. Sessions expire after 15 minutes, expired rows are discarded on the next verified session creation, and logout deletes that session. Machine verification data and bearer tokens belong exclusively in HTTPS request bodies or headers.

Run `python -m unittest discover -s tests` in the desktop Python environment for updater and presence-client tests. Run `node --test service/presence.test.mjs` with Node 24 or later for the service tests. To preview the static pages locally, run `python -m http.server 8080 --directory public` and open <http://localhost:8080>.
