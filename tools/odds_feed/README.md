# Odds feed

`fetch_odds.py` reads real games and odds from The Odds API and writes `odds.json`; the workflow `.github/workflows/odds-feed.yml` runs it on a schedule and publishes the
file to the `odds-data` branch, which the game reads. In-game money only.

Setup (once): make an account at https://the-odds-api.com, copy the API key, and add it to this repository as a secret named `ODDS_API_KEY`
(Settings > Secrets and variables > Actions). Run the workflow once by hand (Actions > Odds feed > Run workflow) to check it.

Credits: the `/sports` call is free; `/odds` costs 1 credit per sport that has games; `/scores` costs 2 per sport (it is needed to settle bets). Four sports in season is about
12 credits a run. Check the current plan sizes on the provider's usage-plans page: a free plan fits about one run a day; live odds every 15 to 30 minutes need a paid plan.
Edit `odds_feed_config.json` to change the sports or the watch list.
