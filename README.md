# Havoc Midnight release notes

Cloudflare Pages serves the contents of `public/`. The release notes include five screen previews, full-size desktop captures and the original Midnight artwork. Every asset ships with the site.

## Preview locally

Run `python -m http.server 8080 --directory public` from the project folder, then open <http://localhost:8080>. Each screen has a shareable tab. With scripts disabled, the same links jump to the corresponding articles on one page.

## Publish from GitHub

1. Grant Cloudflare Workers and Pages access to the `yibbbbbbb/havoc-updates-1` repository in GitHub.
2. In **Workers & Pages → Create application → Pages → Connect to Git**, select the repository.
3. Set the production branch to `main`, the framework to **None**, and the build output directory to `public`. Leave the build command and root directory empty.
4. Select **Save and Deploy**. Use the Pages address assigned by Cloudflare. Each subsequent push to `main` redeploys the site.

Change the release copy, date and image descriptions in `public/index.html`. Preserve the section IDs to keep links to existing notes working. Cloudflare applies the security headers in `public/_headers`.

[Cloudflare Pages Git integration](https://developers.cloudflare.com/pages/get-started/git-integration/)
