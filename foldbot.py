from telegram.ext import Updater, InlineQueryHandler, CommandHandler, PicklePersistence
import requests
import re
import logging
from datetime import datetime, timezone
import bz2
import json
from local import BOTTOKEN

def start(update, context):
    chat = update.effective_chat.id
    if not context.bot_data.get('global_init', False):
        context.bot_data['global_init'] = True
        context.bot_data['teamurl'] = 'https://apps.foldingathome.org/daily_team_summary.txt.bz2'
        context.bot_data['donorurl'] = 'https://apps.foldingathome.org/daily_user_summary.txt.bz2'
        context.bot_data['lastmodt'] = datetime.fromtimestamp(0)
        context.bot_data['lastmodd'] = datetime.fromtimestamp(0)
        context.bot_data['teams'] = {}
        context.bot_data['members'] = {}
        context.bot_data['donors'] = {}
    teams = context.bot_data['teams']
    if 'hometeam' in context.chat_data and context.chat_data['hometeam'] in teams:
        context.bot.send_message(chat_id=chat,
               text="Folders of {0}, let's roll!".format(teams[context.chat_data['hometeam']]['name']))
    else:
        context.bot.send_message(chat_id=chat, text="I'm a folding bot, like Optimus Prime.")
    # No references to jobs can be stored in bot/chat_data because Pickle will choke on it
    # So we have to just make sure a job is running for each chat and give it a predictable name
    # so we can find it in the queue again
    for j in context.job_queue.get_jobs_by_name('updatescores-' + str(chat)):
        print ('removing', j)
        j.schedule_removal()
    context.chat_data['lastcheck'] = datetime.fromtimestamp(0,tz=timezone.utc)
    context.job_queue.run_repeating(updatescores, interval=300,
                                    context=[chat, context.chat_data],
                                    name='updatescores-' + str(chat))
        

def get_url():
    contents = requests.get('https://random.dog/woof.json').json()
    url = contents['url']
    return url

def bop(update, context):
    url = get_url()
    chat_id = update.effective_chat.id
    context.bot.send_photo(chat_id=chat_id, photo=url)

def setteam(update, context):
    if len(context.args) > 0: 
        context.chat_data['hometeam'] = context.args[0]
        for j in context.job_queue.get_jobs_by_name('updatescores-' + str(update.effective_chat.id)):
            print ('removing', j)
            j.schedule_removal()
        context.chat_data['lastcheck'] = datetime.fromtimestamp(0,tz=timezone.utc)
        context.job_queue.run_repeating(updatescores, interval=300,
                                    context=[update.effective_chat.id,
                                    context.chat_data], name='updatescores-' + str(update.effective_chat.id))
        
        if context.args[0] not in context.bot_data['teams']:
            context.bot.send_message(chat_id=update.effective_chat.id, text='WARNING: Team {0} not found.'.format(context.args[0]))
        else: 
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text='Now following team: {0} - {1}.'.format(context.args[0],
                                      context.bot_data['teams'][context.args[0]]['name']))
    else:
        tid = context.chat_data.get('hometeam', 'not set')
        context.bot.send_message(chat_id=update.effective_chat.id, text='Following team: {0}.'.format(tid))

def update_stats(context):
    # 1. if team data has refreshed, rebuild 'teams' dict with total score, rank, wu
    # 2. if donor data has refreshed, (a) rebuild 'donors' dict (sum of contributions per donor across teams)
    #                                 (b) rebuild 'members' dict (individual contributrions per donor to each team)
    if 'teamurl' not in context.bot_data: return  # we have not run start yet, anywhere.
    teamurl = context.bot_data['teamurl']
    r = requests.head(teamurl)
    d = datetime.strptime(r.headers['last-modified'],'%a, %d %b %Y %H:%M:%S %Z')
    teams = context.bot_data['teams']
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
                    print('Continued line {0}: {1}'.format(rank, '|'.join(teamfields)))
                    tbc = False
                    (score, wu) = teamfields[-2:] # there may be more of the name field, but those assholes don't deserve the effort
                    teams[team] = {k: v for k, v in (('name', name), ('score', score), ('wu', wu), ('rank', rank))}
                    continue
                rank += 1
                try:
                    (team, name, score, wu) = teamfields
                except:
                    print('There was a problem with line {0}: {1}'.format(rank, '|'.join(teamfields)))
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
            # timestamping to help chat-based update jobs know when there might be work to do
            context.bot_data['updated'] = datetime.now(timezone.utc)
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
                    print ('WARNING: There was a problem with the following donor: ' + donorline.decode('utf-8'))
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
            context.bot_data['updated'] = datetime.now(timezone.utc)

def setmilestones(update, context):
    team = None
    if 'hometeam' in context.chat_data:
        team = context.chat_data['hometeam'] #use team id if can't lookup name
        if team in context.bot_data['teams']:
            team = context.bot_data['teams'][team]['name']
    teamstr = " for team " + team if team else ""
    if len(context.args) == 0:
        msr = "" if context.chat_data.get('milestones', False) else " not"
        context.bot.send_message(chat_id=update.effective_chat.id, text='milestones are{0} set{1}.'.format(msr, teamstr))
        return
    if len(context.args) == 1:
        if context.args[0] == 'on':
            if context.chat_data.get('milestones', False):
                context.bot.send_message(chat_id=update.effective_chat.id,
                                         text='milestones are already being reported{0}.'.format(teamstr))
                return
            context.chat_data['milestones'] = True
                                                                        
            if not team:
                context.bot.send_message(chat_id=update.effective_chat.id,
                                         text='WARNING: milestones set, but no team to report on\nUse /team to set a team')
            else:
                context.bot.send_message(chat_id=update.effective_chat.id, text='milestones will be reported{0}.'.format(teamstr))
              
            return
        if context.args[0] == 'off':
            if not context.chat_data.get('milestones', False):
                context.bot.send_message(chat_id=update.effective_chat.id,
                                         text='milestone reporting is already off{0}.'.format(teamstr))
                return
            context.chat_data['milestones'] = False
            context.bot.send_message(chat_id=update.effective_chat.id, text='milestones will not be reported{0}.'.format(teamstr))
            return
    context.bot.send_message(chat_id=update.effective_chat.id, text='usage: /milestones [on|off]')

def updatescores(context):
    chat_id = context.job.context[0]
    chat_data = context.job.context[1]
    if 'hometeam' not in chat_data: return # nothing to do
    # some shorthand references
    if chat_data['lastcheck'] > context.bot_data['updated']: return
    chat_data['lastcheck'] = datetime.now(timezone.utc)
    team = chat_data['hometeam']
    teams = context.bot_data['teams']
    donors = context.bot_data['donors']
    members = context.bot_data['members']
    if team not in teams: return # probably should warn here
    teamname = teams[team]['name']
    newscores = {}
    newscores[teamname] = { 'teamrank': 0, 'fullrank': teams[team]['rank'],
                                      'wu': teams[team]['wu'], 'score': teams[team]['score'] }
    for name in members[team]:
        newscores[name] = { 'teamrank': members[team][name]['teamrank'], 'fullrank': donors[name]['rank'],
                                      'wu': members[team][name]['wu'], 'score': members[team][name]['score'] }
    if 'scores' in chat_data and teamname in chat_data['scores'] and chat_data.get('milestones',False):
        # not first call, didn't switch teams, and reporting is on
        scores = chat_data['scores']
        for name in newscores.keys():
            forteam = " for " + teamname if name != teamname else ""
            if name not in scores:
                context.bot.send_message(chat_id=chat_id,
                                         text='New member: {0} has joined {1}!'.format(name, teamname))
            elif name != teamname and newscores[name]['teamrank'] < scores[name]['teamrank']:
                context.bot.send_message(chat_id=chat_id,
                                         text='{0} has advanced to rank {1} in {2}!'.format(name,
                                              newscores[name]['teamrank'], teamname))
            done = False
            steps = [1, 2, 5]
            while not done and name in scores: # too lazy to come up with a smart way to do this
                for step in steps:
                    done = True
                    if step >= newscores[name]['fullrank']:
                        if step < scores[name]['fullrank']:
                           context.bot.send_message(chat_id=chat_id,
                                         text='{0} is now in the overall top {1}!'.format(name, step))
                    else:
                        done = False
                    if step > int(scores[name]['wu']):
                        if step <= int(newscores[name]['wu']):
                           context.bot.send_message(chat_id=chat_id,
                                         text='{0} has processed {1} work units{2}!'.format(name, step, forteam))
                    else:
                        done = False
                    if step > int(scores[name]['score']):
                        if step <= int(newscores[name]['score']):
                           context.bot.send_message(chat_id=chat_id,
                                         text='{0} has earned {1} credit{2}!'.format(name, step, forteam))
                    else:
                        done = False
                # https://stackoverflow.com/questions/4081217/how-to-modify-list-entries-during-for-loop
                steps[:] = [x * 10 for x in steps]

    # done reporting, update values.
    chat_data['scores'] = newscores

def getstats(update, context):
    if 'hometeam' not in context.chat_data:
        context.bot.send_message(chat_id=update.effective_chat.id, text='Please set a team with /team first.')
        return
    if 'scores' not in context.chat_data:
        context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry I've just woken up.  No stats yet")
        return
    team = context.chat_data['hometeam']
    teams = context.bot_data['teams']
    teamname = teams[team]['name']
    scores = context.chat_data['scores']
    message = 'Team: {0}({name}) - Credit: {score} Rank: {rank} WU: {wu}.'.format(team, **teams[team])
    for name in sorted(scores, key=lambda x: scores[x]['teamrank']):
        if name == teamname: continue
        message += '\n{teamrank}. ({fullrank})   \t{0}   \tCredit: {score}   \tWU: {wu}'.format(name, **scores[name])
    print("Stats message: " + message)
    context.bot.send_message(chat_id=update.effective_chat.id, text=message)
        

def main():
    updater = Updater(token=BOTTOKEN,
                      persistence=PicklePersistence(filename='foldbot.dat'),
                      use_context=True)
    dp = updater.dispatcher
    jq = updater.job_queue
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        level=logging.INFO)
    dp.add_handler(CommandHandler('start',start))
    dp.add_handler(CommandHandler('woof',bop))
    dp.add_handler(CommandHandler('team',setteam))
    dp.add_handler(CommandHandler('milestones',setmilestones))
    dp.add_handler(CommandHandler('stats',getstats))
    #dp.add_handler(CommandHandler('stats',setstats))
    jq.run_repeating(update_stats, interval=900, first=30)
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
