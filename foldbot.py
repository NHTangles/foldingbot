from telegram.ext import Updater, InlineQueryHandler, CommandHandler, PicklePersistence
from telegram import ParseMode
import requests
import re
import logging
from datetime import datetime, timezone, time
import bz2
import json
from local import BOTTOKEN

def init(context):
    log = logging.getLogger('foldbot')
    log.info('init called - starting up.')
    if not context.bot_data.get('global_init', False):
        log.warning('init - initialising global state from scratch...')
        context.bot_data['global_init'] = True # so we know we've been here (or read persistent state from file)
        context.bot_data['teamurl'] = 'https://apps.foldingathome.org/daily_team_summary.txt.bz2'
        context.bot_data['donorurl'] = 'https://apps.foldingathome.org/daily_user_summary.txt.bz2'
        context.bot_data['lastmodt'] = datetime.fromtimestamp(0) # last modified header TEAMS url
        context.bot_data['lastmodd'] = datetime.fromtimestamp(0) # last modified header DONORS url
        context.bot_data['teams'] = {} # team data read from downloaed file
        context.bot_data['members'] = {} # team scores broken down by member
        context.bot_data['subs'] = {} # Chats subscribed to each team
        context.bot_data['donors'] = {} # full list of donors with total wu/points and list of teams they contributed to
        context.bot_data['milestones'] = [] # list of chat_ids that are subscribed to 'milestone' updates
        context.bot_data['scores'] = {} # dict of curent scores per member per subscribed team (and team totals)

def start(update, context):
    chat = update.effective_chat.id
    teams = context.bot_data['teams']
    if 'hometeam' in context.chat_data and context.chat_data['hometeam'] in teams:
        context.bot.send_message(chat_id=chat,
               text="Folders of {0}, let's roll!".format(teams[context.chat_data['hometeam']]['name']))
    else:
        context.bot.send_message(chat_id=chat, text="I'm a folding bot, like Optimus Prime.")
        context.bot.send_message(chat_id=chat, text='Please set your team with "/team <teamNum>", or type "/help" for more')

def get_url():
    contents = requests.get('https://random.dog/woof.json').json()
    url = contents['url']
    return url

def bop(update, context):
    url = get_url()
    chat_id = update.effective_chat.id
    context.bot.send_photo(chat_id=chat_id, photo=url)

def getcert(update, context):
    chat_id = update.effective_chat.id
    try: team = context.chat_data['hometeam']
    except:
        context.bot.send_message(chat_id=chat_id, text="No team. Please set with /team <team id>")
        return
    url = 'https://apps.foldingathome.org/awards?team={0}&time={1}'.format(team, datetime.now().timestamp())
    context.bot.send_photo(chat_id=chat_id, photo=url)

def setteam(update, context):
    cd = context.chat_data
    bd = context.bot_data
    chat = update.effective_chat.id
    log = logging.getLogger('foldbot')
    if len(context.args) > 0:
        # if 'hometeam' in cd and cd['hometeam'] in bd['subs'] and chat in bd['subs'][cd['hometeam']]:
        # blah blah... forgiveness, not permission
        try:
           bd['subs'][cd['hometeam']].remove(chat)
        except:
           pass
        try:
           if len(bd['subs'][cd['hometeam']]) == 0:
               del bd['subs'][cd['hometeam']]
        except:
           pass
        tid = context.args[0]
        cd['hometeam'] = tid
        cd['lastcheck'] = datetime.fromtimestamp(0,tz=timezone.utc)
        if tid not in bd['subs']:
            bd['subs'][tid] = []
        bd['subs'][tid].append(chat)

        if context.args[0] not in bd['teams']:
            context.bot.send_message(chat_id=chat, text='WARNING: Team {0} not found.'.format(tid))
        else:
            context.bot.send_message(chat_id=chat,
                                     text='Now following team: {0} - {1}.'.format(tid,
                                      bd['teams'][tid]['name']))
    else:
        tid = context.chat_data.get('hometeam', 'not set')
        context.bot.send_message(chat_id=update.effective_chat.id, text='Following team: {0}.'.format(tid))

def update_stats(context):
    # 1. if team data has refreshed, rebuild 'teams' dict with total score, rank, wu
    # 2. if donor data has refreshed, (a) rebuild 'donors' dict (sum of contributions per donor across teams)
    #                                 (b) rebuild 'members' dict (individual contributrions per donor to each team)
    log = logging.getLogger('foldbot')
    log.info('update_stats')
    if 'teamurl' not in context.bot_data: return  # not initialised - should not happen
    teamurl = context.bot_data['teamurl']
    r = requests.head(teamurl)
    d = datetime.strptime(r.headers['last-modified'],'%a, %d %b %Y %H:%M:%S %Z')
    teams = context.bot_data['teams']
    updated = False
    if d > context.bot_data['lastmodt']:
        r = requests.get(teamurl)
        if r.ok:
            context.bot_data['lastmodt'] = d
            teams = {}
            rank = 0
            tbc = False
            for teamline in bz2.decompress(r.content).splitlines()[2:]:
                #print(teamline.decode('utf-8').split('\t'))
                teamfields = teamline.decode('utf-8').split('\t')
                if tbc: # see 'except' below
                    log.info('Continued line {0}: {1}'.format(rank, '|'.join(teamfields)))
                    tbc = False
                    (score, wu) = teamfields[-2:] # there may be more of the name field, but those assholes don't deserve the effort
                    teams[team] = {k: v for k, v in (('name', name), ('score', score), ('wu', wu), ('rank', rank))}
                    continue
                rank += 1
                try:
                    (team, name, score, wu) = teamfields
                except:
                    log.warning('There was a problem with line {0}: {1}'.format(rank, '|'.join(teamfields)))
                    (team, name) = teamfields[0:2]
                    if len(teamfields) < 4:
                        # some jerks put line breaks in their team name because they can.
                        tbc = True
                        continue
                    else:
                        # this is for the singular bag of dicks that put tabs in the team name
                        # They lose everything after the first tab. Screw them.
                        (score, wu) = teamfields[-2:]
                teams[team] = {k: v for k, v in (('name', name), ('score', score), ('wu', wu), ('rank', rank))}
            context.bot_data['teams'] = teams
            updated = True
    donorurl = context.bot_data['donorurl']
    r = requests.head(donorurl)
    d = datetime.strptime(r.headers['last-modified'],'%a, %d %b %Y %H:%M:%S %Z')
    if d > context.bot_data['lastmodd']:
        r = requests.get(donorurl)
        if r.ok:
            context.bot_data['lastmodd'] = d
            donors = {}
            members = {}

            for donorline in bz2.decompress(r.content).splitlines()[2:]:
                try:
                    (name, score, wu, team) = donorline.decode('utf-8').split('\t')
                except:
                    log.warning('There was a problem with the following donor: ' + donorline.decode('utf-8'))
                    continue
                if name not in donors: donors[name] = {}
                donors[name]['wu'] = donors[name].get('wu', 0) + int(wu)
                donors[name]['score'] = donors[name].get('score', 0) + int(score)
                donors[name]['teams'] = donors[name].get('teams', []) + [team]
                if team not in members:
                    members[team] = {}
                members[team][name] = { 'score': score, 'wu': wu }
                # assumes the donor list is sorted by max score, which it appears to be
                members[team][name]['teamrank'] = len(members[team].keys())

            # Now the fun part: rank each donor by total score.
            rank = 0
            for donor in sorted(donors, key=lambda x: donors[x]['score'], reverse=True):
                rank += 1
                donors[donor]['rank'] = rank
            context.bot_data['donors'] = donors
            context.bot_data['members'] = members
            updated = True
    if updated:
        updatescores(context)

def setmilestones(update, context):
    team = None
    chat = update.effective_chat.id
    if 'hometeam' in context.chat_data:
        team = context.chat_data['hometeam'] #use team id if can't lookup name
        if team in context.bot_data['teams']:
            team = context.bot_data['teams'][team]['name']
    teamstr = " for team " + team if team else ""
    if len(context.args) == 0:
        msr = "" if chat in context.bot_data['milestones'] else " not"
        context.bot.send_message(chat_id=chat, text='milestones are{0} set{1}.'.format(msr, teamstr))
        return
    if len(context.args) == 1:
        if context.args[0] == 'on':
            if chat in context.bot_data['milestones']:
                context.bot.send_message(chat_id=chat,
                                         text='milestones are already being reported{0}.'.format(teamstr))
                return
            context.bot_data['milestones'].append(chat)

            if not team:
                context.bot.send_message(chat_id=chat,
                                         text='WARNING: milestones set, but no team to report on\nUse /team to set a team')
            else:
                context.bot.send_message(chat_id=chat, text='milestones will be reported{0}.'.format(teamstr))
            return

        if context.args[0] == 'off':
            if chat not in context.bot_data['milestones']:
                context.bot.send_message(chat_id=chat,
                                         text='milestone reporting is already off{0}.'.format(teamstr))
                return
            context.bot_data['milestones'].remove(chat)
            context.bot.send_message(chat_id=chat, text='milestones will not be reported{0}.'.format(teamstr))
            return
    context.bot.send_message(chat_id=update.effective_chat.id, text='usage: /milestones [on|off]')

def send_milestone(context, team, message):
    for chat in context.bot_data['subs'][team]:
        if chat in context.bot_data['milestones']:
            context.bot.send_message(chat_id=chat,  disable_notification=True, text=message)

def updatescores(context):
    #chat_id = context.job.context[0]
    #chat_data = context.job.context[1]
    #if 'hometeam' not in chat_data: return # nothing to do
    # Pretty formatting
    numbers = { 1000000: "one million",
                2000000: "two million",
                5000000: "five million",
               10000000: "ten million",
               20000000: "20 million",
               50000000: "50 million",
              100000000: "100 million",
              200000000: "200 million",
              500000000: "500 million",
             1000000000: "one billion",
             2000000000: "two billion",
             5000000000: "five billion" }

    log = logging.getLogger('foldbot')
    # some shorthand references
    teams = context.bot_data['teams']
    donors = context.bot_data['donors']
    members = context.bot_data['members']
    subs = context.bot_data['subs']

    for team in subs:
        log.info('updatescores - team: {0}'.format(team))
        if team not in teams:
            log.warning ("Team {0} Not foud - not updating".format(team))
            continue
        teamname = teams[team]['name']
        newscores = {}
        newscores[teamname] = { 'teamrank': 0, 'fullrank': teams[team]['rank'],
                                      'wu': teams[team]['wu'], 'score': teams[team]['score'] }
        for name in members[team]:
            newscores[name] = { 'teamrank': members[team][name]['teamrank'], 'fullrank': donors[name]['rank'],
                                      'wu': members[team][name]['wu'], 'score': members[team][name]['score'] }
        if team in context.bot_data['scores']:
            scores = context.bot_data['scores'][team]
            for name in newscores.keys():
                forteam = " for " + teamname if name != teamname else ""
                if name not in scores:
                    send_milestone(context, team,
                                   'New member: {0} has joined {1}!'.format(name, teamname))
                elif name != teamname and newscores[name]['teamrank'] < scores[name]['teamrank']:
                    send_milestone(context, team,
                                   '{0} has advanced to rank {1} in {2}!'.format(name,
                                              newscores[name]['teamrank'], teamname))
                done = False
                steps = [1, 2, 5]
                while not done and name in scores: # too lazy to come up with a smart way to do this
                    for step in steps:
                        done = True
                        if step >= newscores[name]['fullrank']:
                            if step < scores[name]['fullrank']:
                                send_milestone(context, team,
                                    '{0} is now in the overall top {1}!'.format(name, numbers.get(step,step)))
                        else:
                            done = False
                        if step > int(scores[name]['wu']):
                            if step <= int(newscores[name]['wu']):
                                send_milestone(context, team,
                                   '{0} has processed {1} work units{2}!'.format(name, numbers.get(step,step), forteam))
                        else:
                            done = False
                        if step > int(scores[name]['score']):
                            if step <= int(newscores[name]['score']):
                               send_milestone(context, team,
                                   '{0} has earned {1} credit{2}!'.format(name, numbers.get(step,step), forteam))
                        else:
                            done = False
                    # https://stackoverflow.com/questions/4081217/how-to-modify-list-entries-during-for-loop
                    steps[:] = [x * 10 for x in steps]

        # done reporting, update values.
        context.bot_data['scores'][team] = newscores

def getstats(update, context):
    if 'hometeam' not in context.chat_data:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Please set a team with /team first.')
        return
    team = context.chat_data['hometeam']
    if  team not in context.bot_data['scores']:
        context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry I've just woken up.  No stats yet")
        return
    teams = context.bot_data['teams']
    teamname = teams[team]['name']
    scores = context.bot_data['scores'][team]
    message = 'Team: {0}({name})\nCredit: {score} Rank: {rank} WU: {wu}.'.format(team, **teams[team])
    for name in sorted(scores, key=lambda x: scores[x]['teamrank']):
        if name == teamname: continue
        frank = '({0})'.format(scores[name]['fullrank'])
        message += '\n{teamrank: >2}.{frank: >8} {name: <16}Cr:{score: >9} WU:{wu: >4}'.format(name=name, frank=frank, **scores[name])
    #print("Stats message: " + message)
    context.bot.send_message(chat_id=update.effective_chat.id, text='`' + message + '`', parse_mode=ParseMode.MARKDOWN_V2)

def dailies(context):
    if 'daily' not in context.bot_data: context.bot_data['daily'] = {}
    daily = context.bot_data['daily']
    subs = context.bot_data['subs']
    milestones = context.bot_data['milestones']
    scores = context.bot_data['scores']
    teams = context.bot_data['teams']
    members = context.bot_data['members']
    for team in subs:
        if team in daily:
            teamname = teams[team]['name']
            message = 'Last 24h: {0}({name}) - Credit: {score} WU: {wu}.'.format(team,
                      name = teamname,
                      wu =  int(teams[team]['wu']) - int(daily[team]['wu']),
                      score = int(teams[team]['score']) - int(daily[team]['score']))

            delta = {}
            for name in members[team]:
                delta[name] = { 'wu'   : int(members[team][name]['wu'])
                                        - (daily[team][name]['wu'] if name in daily[team] else 0),
                                'score': int(members[team][name]['score'])
                                        - (daily[team][name]['score'] if name in daily[team] else 0) }

            rank = 0
            for name in sorted(delta, key=lambda x: delta[x]['score'], reverse=True):
                rank += 1
                if int(delta[name][score]) > 0:
                    message += '\n{rank: >2}. {name: <16}Credit:{score: >7} WU:{wu: >3}'.format(rank=rank, name=name, **delta[name])

            for chat in context.bot_data['subs'][team]:
                if chat in milestones:
                    context.bot.send_message(chat_id=chat,  disable_notification=True,
                                             text='`' + message + '`',
                                             parse_mode=ParseMode.MARKDOWN_V2)
        # Ugh this shit will break if someone names themself 'score' or 'wu' - TODO: fix.
        daily[team] = { 'wu': teams[team]['wu'], 'score': teams[team]['score'] }
        for name in members[team]:
            daily[team][name] = { 'wu'   : int(members[team][name]['wu']),
                                  'score': int(members[team][name]['score']) }
    for team in daily:
        if team not in subs: del daily[team]

def listcmds(update, context):
    msg = ''
    for (name, callback, desc) in commands:
        msg += '/{0}: {1}\n'.format(name, desc)
    context.bot.send_message(chat_id=update.effective_chat.id, text = msg)

commands = [('start', start, 'Start a session with the bot - provides some basic instructions'),
            ('team', setteam, 'Tell the bot which team you or your chatgroup is following'),
            ('milestones', setmilestones, 'Turn on/off reporting of folding milsetones for your team or its members'),
            ('stats', getstats, 'Print current stats for your team or its members'),
            ('cert', getcert, 'Show the current folding award certificate for the team'),
            ('help', listcmds, 'Show this list of commands and what they do'),
            ('woof', bop, 'Print a doggy picture, for no reason') ]

def main():
    updater = Updater(token=BOTTOKEN,
                      persistence=PicklePersistence(filename='foldbot.dat'),
                      use_context=True)
    dp = updater.dispatcher
    jq = updater.job_queue
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        level=logging.INFO)
    jq.run_once(init, when=0)
    for (name, callback, desc) in commands:
        dp.add_handler(CommandHandler(name, callback))

    jq.run_repeating(update_stats, interval=600, first=10)
    jq.run_daily(dailies, time(hour=0))
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
