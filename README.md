# 🌸 Nova — Aksys Games & Otomate News Bot

Free news monitoring for **Aksys Games** and **Otomate (Japan)**, posted to a Discord channel every three hours.

- English announcements from https://www.aksysgames.com/blog/
- Japanese headlines from https://www.otomate-p.jp/news/ translated into English using Argos Translate (offline, no AI API fee)
- Original Japanese headlines and source links included
- No duplicate posting: `state.json` is maintained by the GitHub Action
- First successful check of each site initializes its history without flooding Discord
- No server, no OpenAI API key, no paid translations

## Connect Discord

1. In the desired Discord text channel, use **Edit Channel → Integrations → Webhooks → New Webhook**.
2. Name it **Nova News Bot**, select the channel, and **Copy Webhook URL**.
3. In this GitHub repository open **Settings → Secrets and variables → Actions → New repository secret**.
4. Name the secret `DISCORD_WEBHOOK_URL`, and set its value to the webhook URL. **Never commit or share this URL.**

## First run

1. Go to the repository **Actions** tab. Enable workflows if prompted.
2. Select **Nova - Aksys and Otomate News** → **Run workflow**.
3. Set `send_test_message` to **true** to send a harmless connection test to Discord.
4. Run again with `send_test_message` **false**. This checks both news sites and records the existing stories without reposting them.
5. Future new announcements post automatically. GitHub schedule execution might be delayed during busy periods.

The workflow needs permission to push `state.json`. Under **Settings → Actions → General → Workflow permissions**, allow write permissions if necessary. Branch protection rules may also block that push.

## Costs

No API fee, no continuously running machine. GitHub Free currently includes **2,000 Actions minutes per month** for private repositories; usage beyond allowances can incur charges depending on account billing configuration. Approx. 240 runs per month at three-hour intervals. Keep an eye on GitHub **Settings → Billing** and workflow execution duration. An offline Japanese translation model downloads when the first new Japanese announcement is detected; the cache helps subsequent runs.

## Limitations

Japanese *headlines*, not entire articles, are translated. Machine translation can be imperfect, so retain the source title and URL. Japanese announcements are not necessarily English localizations. This simple page monitor may require maintenance when either site changes its layout.

Local tests: `python -m unittest discover -s tests -v`. Run locally with `DISCORD_WEBHOOK_URL` set in your environment.
