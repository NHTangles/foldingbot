This is a Telegram bot for tracking your Folding@Home team's progress.

Basic instructions - create a telegram group for yout F@H team, add @FoldingBot to the group.

Run the following:

/team YOUR_TEAM_NUMBER (tells the bot what team your chat group is following)

/milsetones on (tells the bot to notify the group when rankings within team change or significant milestones are reached - optional)

To check your team's current stats, type

/stats

If stats stop updating it's possible that the bot has been restarted and the update job isn't running, this can be reset with:

/start

If you want to run your own version of this, register a bot with BotFather, and place the bot token in local.py (see local.py.template)

then run the bot like this:

python3 foldbot.py
