import webapp2, os, logging, json
from google.appengine.ext import ndb
from utils.consts import *
from models.Feedler import Feedler
from models.Trigger import *
import utils.query as Query
import utils.queuer as Queuer
from datetime import datetime, timedelta

#A helper class to fetch all of the Feedler's at the same
#time and only fetch a Feedler once
class _FeedlerTracker(object):
    feedlers = {}

    #On init, grab all of the Feedlers
    def __init__(self, triggers):
        feedler_unique = {}

        for trigger in triggers:
            fk = trigger.feedler_key
            fi = fk.id()

            #Only add unique feedlers
            if fi not in feedler_unique:
                feedler_unique[fi] = fk

        #Now grab all the Feedlers in one request
        feedler_keys = feedler_unique.values()
        feedler_list = ndb.get_multi(feedler_keys)

        #Now save the Feedlers in the class property dict
        for feedler in feedler_list:
            fk = feedler.key
            fi = fk.id()

            if fi not in self.feedlers:
                self.feedlers[fi] = feedler

    #Returns a Trigger's Feedler
    def get_feedler(self, trigger):
        feedler_id = trigger.feedler_key.id()
        #I could check to make sure it exists, but there's no reason
        #it shouldn't
        return self.feedlers[feedler_id]

#Find Triggers that need to run
class QueueTriggersCronHandler(webapp2.RequestHandler):
    def get(self):

        #Only grab triggers that need to be run
        time_limit = datetime.now() - timedelta(minutes=RUN_TRIGGER_EVERY_MINUTE)
        triggers = Query.trigger_to_run(time_limit, limit=TRIGGER_CRON_LIMIT)

        #If there's no triggers, then duh we are done
        if len(triggers) == 0:
            return

        #Create the Feedler Tracker to fetch all of the Feedlers
        feedler_tracker = _FeedlerTracker(triggers)

        for trigger in triggers:
            #Grab the Feedler from memory
            feedler = feedler_tracker.get_feedler(trigger)

            #Don't run the Trigger if the Feedler can't run Triggers
            if feedler.can_run_triggers:
                Queuer.run_trigger(trigger)

app = webapp2.WSGIApplication([
    ('/cron/trigger/queue', QueueTriggersCronHandler)
], debug=True)