# Polymarket Opportunity Bot

This Python bot monitors Polymarket in real-time, detects a variety of trading opportunities based on configurable patterns, and sends instant alerts to a Telegram channel.

It is designed to be lightweight, easy to configure, and deployable on free-tier or low-cost cloud services.

---

## Features

- **Real-Time Monitoring**: Continuously polls Polymarket's public APIs for the latest market data.
- **Configurable Strategies**: Detects opportunities using a modular and fully configurable engine.
- **Telegram Alerts**: Delivers rich, informative, and actionable alerts directly to your Telegram.
- **Easy Setup**: Get up and running in minutes with minimal configuration.
- **Deploy Anywhere**: Includes instructions for local testing and deployment on Railway, a VPS, or AWS Lambda.

### Detection Patterns

The bot can identify the following types of market opportunities:

1.  **Sudden Odds Shifts**: Flags markets where the implied probability changes significantly over a short period (e.g., >10% in 24 hours).
2.  **High Volume Spikes**: Identifies markets experiencing unusually high trading volume compared to their recent average, often indicating new information or interest.
3.  **Markets About to Resolve**: Alerts for markets nearing their end date that haven't yet resolved to 0% or 100%, offering a potential last-minute edge.
4.  **New Markets**: Finds newly created markets with sufficient liquidity, providing an opportunity to get in before the market fully prices in all available information.
5.  **Mispriced Markets**: In multi-outcome events (e.g., "Who will win the election?"), it checks if the sum of all outcome probabilities deviates significantly from 100%, indicating a potential arbitrage or mispricing opportunity.

---

## File Structure

```
/home/ubuntu/polymarket-bot/
├── .env.example          # Template for environment variables
├── .gitignore
├── Dockerfile            # For containerized deployment
├── Procfile              # For PaaS deployment (e.g., Railway, Heroku)
├── README.md             # This file
├── bot.py                # Main application entry point
├── config.py             # Loads and manages all configuration
├── detectors.py          # Core logic for all opportunity detection strategies
├── polymarket_client.py  # Handles all communication with Polymarket APIs
├── requirements.txt      # Python dependencies
└── telegram_alerts.py    # Handles formatting and sending of Telegram messages
```

---

## Setup and Configuration

### Step 1: Prerequisites

- Python 3.10 or newer.
- `git` for cloning the repository.

### Step 2: Clone the Repository

```bash
git clone <repository_url>  # Replace with the actual repo URL
cd polymarket-bot
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Set Up the Telegram Bot

1.  **Create a New Bot with BotFather**:
    - Open Telegram and start a chat with [@BotFather](https://t.me/BotFather).
    - Send the `/newbot` command.
    - Follow the prompts to choose a name and username for your bot.
    - BotFather will give you a **Bot Token**. Copy it.

2.  **Find Your Chat ID**:
    - Start a chat with your newly created bot by clicking the `t.me/<your_bot_username>` link from BotFather.
    - Send any message to your bot (e.g., `/start`).
    - Now, you need to get the ID of this private chat. The easiest way is to use a helper bot like [@userinfobot](https://t.me/userinfobot).
    - Start a chat with `@userinfobot` and it will immediately tell you your User ID. This is your `TELEGRAM_CHAT_ID` for a private channel.
    - *Alternatively*, if you want to send alerts to a group, add your bot to the group and then send a message in the group. Then, open this URL in your browser: `https://api.telegram.org/bot<YourBotToken>/getUpdates` (replace `<YourBotToken>` with your token). Look for the `"chat": {"id": ...}` field; the `id` (which is usually a negative number) is your group's Chat ID.

### Step 5: Configure the Bot

1.  Copy the example environment file:
    ```bash
    cp .env.example .env
    ```

2.  Open the `.env` file in a text editor and fill in the required values:
    - `TELEGRAM_BOT_TOKEN`: The token you got from BotFather.
    - `TELEGRAM_CHAT_ID`: The chat ID you found in the previous step.

3.  (Optional) Adjust the thresholds and settings in the `.env` file to match your preferences. The default values are sensible starting points.

---

## Running the Bot

### Running Locally

To run the bot for testing or development, simply execute the `bot.py` script:

```bash
python bot.py
```

The bot will send a startup message to your Telegram channel and begin polling Polymarket.

#### Command-Line Arguments

- `--once`: Run a single scan cycle and then exit. Useful for testing your configuration without starting a continuous loop.
- `--dry-run`: Fetch data and run all detectors, but print the alerts to the console instead of sending them to Telegram. This is the safest way to test new thresholds or topic filters.

```bash
# Test one cycle and print alerts to the console
python bot.py --once --dry-run
```

---

## Deployment

You can deploy this bot on any server that runs Python. Here are guides for a few popular, low-cost options.

### Option 1: Railway (PaaS)

Railway is one of the easiest platforms for deploying worker bots. It can deploy directly from a GitHub repository.

1.  **Create a GitHub Repository**: Push the bot's code to a new public or private GitHub repository.
2.  **Sign Up for Railway**: Create a free account on [railway.app](https://railway.app).
3.  **Create a New Project**: From your Railway dashboard, click "New Project" and select "Deploy from GitHub Repo". Choose your repository.
4.  **Add Environment Variables**: Once the project is created, go to the "Variables" tab. Copy all the key-value pairs from your local `.env` file and add them here. **Do not commit your `.env` file to GitHub.**
5.  **Deploy**: Railway will automatically detect the `Procfile` (`worker: python bot.py`) and deploy the bot as a background worker. It will start running automatically.

### Option 2: DigitalOcean Droplet (VPS)

This gives you a full Linux server for more control.

1.  **Create a Droplet**: On [DigitalOcean](https://www.digitalocean.com/), create a new Droplet. The cheapest plan (e.g., $4-6/month) is more than sufficient.
2.  **Connect via SSH**: Use SSH to connect to your new server.
3.  **Install Dependencies**:
    ```bash
    sudo apt update
    sudo apt install python3 python3-pip git -y
    ```
4.  **Clone and Set Up the Bot**:
    ```bash
    git clone <your_repo_url>
    cd polymarket-bot
    pip3 install -r requirements.txt
    cp .env.example .env
    nano .env  # Edit the file with your credentials
    ```
5.  **Run Continuously with `systemd` (Recommended)**:
    Create a service file to ensure the bot runs 24/7 and restarts on failure.

    ```bash
    sudo nano /etc/systemd/system/polymarket-bot.service
    ```

    Paste the following content, replacing `/root/polymarket-bot` with the actual path to your bot's directory and `root` with your username if different.

    ```ini
    [Unit]
    Description=Polymarket Alert Bot
    After=network.target

    [Service]
    User=root
    Group=root
    WorkingDirectory=/root/polymarket-bot
    ExecStart=/usr/bin/python3 bot.py
    Restart=always
    RestartSec=10

    [Install]
    WantedBy=multi-user.target
    ```

    Enable and start the service:
    ```bash
    sudo systemctl enable polymarket-bot.service
    sudo systemctl start polymarket-bot.service

    # To check the status and logs:
    sudo systemctl status polymarket-bot
    journalctl -u polymarket-bot -f
    ```

### Option 3: AWS Lambda (Serverless)

This is the most cost-effective option, as you only pay for the exact execution time. This requires adapting the code to a serverless model.

1.  **Modify `bot.py`**: The continuous loop (`while True`) must be replaced with a single handler function that AWS Lambda can call.

    ```python
    # Example handler for Lambda
    def lambda_handler(event, context):
        # The scan_once function already does what we need.
        alerts_sent = scan_once()
        return {
            'statusCode': 200,
            'body': f'Scan complete. Sent {alerts_sent} alerts.'
        }
    ```

2.  **Package for Deployment**: Create a ZIP file containing the code and its dependencies.
    ```bash
    pip install -r requirements.txt -t ./package
    cd package
    zip -r ../deployment.zip .
    cd ..
    zip -g deployment.zip *.py
    ```

3.  **Create a Lambda Function**:
    - In the AWS Console, go to Lambda and create a new function.
    - Choose "Author from scratch", select Python 3.11 runtime.
    - Upload the `deployment.zip` file.
    - In "Configuration" -> "Environment variables", add your `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, etc.
    - Increase the default timeout (under "General configuration") to at least 1 minute.

4.  **Create an EventBridge Trigger**:
    - In the Lambda function's page, click "Add trigger".
    - Select "EventBridge (CloudWatch Events)".
    - Choose "Create a new rule".
    - Select "Schedule expression" and enter `rate(1 minute)` or `rate(5 minutes)`.
    - This will automatically invoke your Lambda function on your desired schedule, effectively replacing the `time.sleep()` loop.

---

## Customization

### Adjusting Thresholds

All detection parameters are in the `.env` file. You can fine-tune them to control the sensitivity and frequency of alerts. For example, to get more "Sudden Odds Shift" alerts, lower the `ODDS_SHIFT_THRESHOLD` from `0.10` to `0.05`.

### Filtering by Topic

To monitor only specific topics (e.g., crypto, politics), edit the `TOPIC_KEYWORDS` variable in your `.env` file:

```
# Monitor only markets related to Bitcoin, Ethereum, or AI
TOPIC_KEYWORDS=bitcoin,ethereum,ai
```

Leave it blank to monitor all markets.
