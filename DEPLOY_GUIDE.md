# How to Deploy Your Polymarket Bot on Railway (24/7)

Hello Linda, this is a simple guide to get your Polymarket Alert Bot running continuously online using a service called Railway. Railway is great because it has a free plan that is perfect for this bot, and it's one of the easiest ways to deploy a project.

Follow these steps, and your bot will be running 24/7 in about 10-15 minutes!

---

### **Step 1: Get the Bot's Code onto GitHub**

First, you need to place the bot's code into a GitHub repository. Think of GitHub as a cloud folder for code. Railway will read the code from there.

1.  **Create a GitHub Account**: If you don't have one, sign up for free at [github.com](https://github.com).

2.  **Create a New Repository**: 
    *   On the GitHub website, click the `+` icon in the top-right corner and select **"New repository"**.
    *   Give it a simple name, like `polymarket-bot`.
    *   Select **"Public"** so Railway can see it.
    *   **Do not** check any boxes like "Add a README file". You want it to be completely empty.
    *   Click **"Create repository"**.

3.  **Upload the Bot Files**:
    *   On your new repository's page, you'll see a section that says "…or upload an existing file". Click that link.
    *   Now, simply **drag and drop all 12 bot files** I sent you into the browser window. The files are:
        *   `bot.py`
        *   `config.py`
        *   `detectors.py`
        *   `polymarket_client.py`
        *   `telegram_alerts.py`
        *   `requirements.txt`
        *   `.env.example`
        *   `README.md`
        *   `Dockerfile`
        *   `Procfile`
        *   `.gitignore`
        *   `.dockerignore`
    *   Once all files are uploaded, type a short message like "Initial commit" in the box at the bottom and click the green **"Commit changes"** button.

Great! Your code is now online.

---

### **Step 2: Create a Railway Account**

1.  Go to [railway.app](https://railway.app).
2.  Click **"Login"** and choose **"Login with GitHub"**. This is the easiest way, as it automatically connects your accounts.
3.  Authorize Railway to access your GitHub account.

---

### **Step 3: Deploy the Bot on Railway**

Now we'll tell Railway to run your bot.

1.  From your Railway dashboard, click **"New Project"**.
2.  Select **"Deploy from GitHub Repo"**.
3.  Find the `polymarket-bot` repository you just created and click on it.
4.  Railway will immediately start analyzing the code and deploying it. You'll see a new service appear with the name of your repository.

---

### **Step 4: Add Your Secret Credentials**

The bot needs your Telegram token and chat ID to work. We'll add these as secret variables.

1.  In your Railway project, click on the service block for your `polymarket-bot`.
2.  Go to the **"Variables"** tab.
3.  You need to add two new variables:
    *   Click **"New Variable"**.
    *   In the "Variable Name" box, type `TELEGRAM_BOT_TOKEN`.
    *   In the "Variable Value" box, paste your bot token: `8394927144:AAEbxf40P5vINoSB8V4HnvoCSqqO7WimKi0`.
    *   Click **"Add"**.

4.  Repeat the process for your Chat ID:
    *   Click **"New Variable"** again.
    *   For the name, type `TELEGRAM_CHAT_ID`.
    *   For the value, paste your chat ID: `6538951592`.
    *   Click **"Add"**.

After you add these variables, Railway will automatically restart your bot with the new settings. This is called a "re-deploy".

---

### **Step 5: Check That It's Running!**

1.  Go to the **"Deployments"** tab in your Railway project.
2.  You should see a recent deployment with a green checkmark and the word **"Success"**. This means the bot is online.
3.  **The final confirmation**: Check your Telegram! The bot should have sent you a startup message that looks like this:

    > **🤖 Polymarket Alert Bot — Online**
    > 
    > Polling every 45s...

If you see that message, your bot is officially live and running 24/7! It will now automatically check Polymarket and send you alerts whenever it finds an opportunity.
