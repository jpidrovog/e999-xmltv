# E999 XMLTV

E999 is a today-only XMLTV feed for ECDF / El Canal del Fútbol.

Why it is today-only:
- the official ECDF `envivo` guide exposes today's lineup
- trying to force a 3-day or 7-day feed produced bad guide data
- this package is designed to publish only today's valid rows with proper start/stop times

## Files

- `scrape_e999.py` - scraper and XMLTV generator
- `requirements.txt` - Python dependencies
- `.github/workflows/publish.yml` - GitHub Actions workflow that publishes to GitHub Pages
- `sample/guide.xml` - example XMLTV output

## What the workflow does

- runs on push to `main`
- can be run manually from the Actions tab
- refreshes every 6 hours
- publishes `public/guide.xml` to GitHub Pages

## Final XMLTV link format

If your repo is named `e999-xmltv` and your GitHub username is `YOURNAME`, the XMLTV URL will be:

`https://YOURNAME.github.io/e999-xmltv/guide.xml`

## Important notes

- the feed is emitted in Ecuador time (`-0500`)
- GitHub Pages may take a minute or two after the first successful workflow run
- if your app runs in another timezone, it may display the guide converted into local time

## Clean setup from scratch

### 1. Create the repository

Create a new GitHub repository named:

`e999-xmltv`

For the easiest setup, do not initialize it with a README, `.gitignore`, or license.

### 2. Upload the project

Unzip the package and upload all files and folders inside it, including `.github`.

### 3. Enable GitHub Pages

In the repository:
- go to `Settings`
- go to `Pages`
- under `Build and deployment`
- set `Source` to `GitHub Actions`

Do not click the suggested starter workflows.

### 4. Run the workflow once manually

In the repository:
- go to `Actions`
- click `Publish E999 XMLTV`
- click `Run workflow`

### 5. Wait for success

When the workflow turns green, open:

`https://YOURNAME.github.io/e999-xmltv/guide.xml`

If it opens and shows XML, the feed is live.

## Dispatcharr settings

Use these values:

- Name: `E999`
- Source Type: `XMLTV`
- URL: your `guide.xml` URL
- Refresh Interval: `6` or `24`

If you want Dispatcharr to display Ecuador local time, make sure the app or container timezone matches `America/Guayaquil`.
