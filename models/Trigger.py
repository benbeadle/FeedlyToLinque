from google.appengine.ext import ndb
from google.appengine.ext.ndb import polymodel
from utils.consts import *
import logging, json, re, webapp2, secrets
from models.Feedler import Feedler

#Since I'm not exactly sure where the article url is, attempt a couple of methods
#to try and get the url from an article
def get_article_url(article):

	if "alternate" in article:
		alternate = [c["href"] for c in article["alternate"] if c["type"] == "text/html"]

		if len(alternate) > 0:
			return alternate[0]

	if "canonical" in article:
		canonical = [c["href"] for c in article["canonical"] if c["type"] == "text/html"]

		if len(canonical) > 0:
			return canonical[0]

	return ""

#This is the main Trigger model. This model contains data all Triggers need
class Trigger(polymodel.PolyModel):
	#The description helps distinguish between different Triggers
	description = ndb.StringProperty('de', required=True, indexed=False)

	#If you linque a device name, it opens the link on the device automatically
	#(not on Android/iOS), so give them the option to linque a device directly
	device_name = ndb.StringProperty('dn', default="", indexed=False)

	link_description = ndb.StringProperty('ld', default="%article_title%", indexed=False)

	#Allows the Feedler to disable Triggers (not run) without having to delete
	#them
	enabled = ndb.BooleanProperty('e', default=True, indexed=True)

	#Keeps track of the last time this Trigger ran
	#There's times when the Trigger is saved and this value should
	#not be updated, which is why I don't use auto_now=True
	last_run = ndb.DateTimeProperty('lr', auto_now_add=True, indexed=True)

	created = ndb.DateTimeProperty('cr', auto_now_add=True, indexed=False)

	#A shortcut to get the base62 version of the Trigger id
	@property
	def id(self):
		return to_base62(self.key.id())

	#A property to reference the Feedler this Trigger belongs to
	#Keep track internally so we can save it in memory
	_feedler = None
	@property
	def feedler(self):
		if self._feedler is None:
			self._feedler = self.feedler_key.get()
		return self._feedler

	@property
	def feedler_key(self):
		return self.key.parent()

	#This returns the last_run property into a timestamp that Feedly's
	#API understances
	@property
	def newer_than(self):
		#This shouldn't happen, but happened during development so just in case
		if self.last_run is None:
			return 0
		return to_unix(self.last_run)

	def get_link_description(self, article):
		title = article["title"]
		ld = self.link_description.replace("%article_title%", title)
		if ld == "":
			return title
		return ld

	#Shortcut to delete the Trigger
	def delete(self):
		self.key.delete()

	#Update the last_run to right now
	def update_last_run(self):
		from datetime import datetime
		self.last_run = datetime.now()
		self.put()

	#This method called the subclass' _run method
	#and updates the last_run value if necessary
	#This method is so the subclasses don't need to worry
	#about updating the last_run property saving code from being duplicated
	def run_block(self, update_last=True):

		#Grab the newer_than property before saving
		newer_than = self.newer_than

		#Save the last_run property before running
		#in case the run takes longer than the cron delay is
		if update_last:
			self.update_last_run()

		result = self._run(newer_than)

		#If there was an error, then disable the Trigger and email the Feedler
		#But only disable if the error is not that the Feedly account is not long authorized
		if "errorCode" in result and result["errorCode"] != 401:
			message = result["errorMessage"] if "errorMessage" in result else ("Unknown Error: %d" % result["errorCode"])
			self.enabled = False
			self.put()

			Emailer.trigger_error(self, message)

		return result

	#This method grabs data from the request and saves it into the Trigger
	#It also calls the subclass' method so each Trigger type can save custom
	#data
	#Also makes sure all data is valid before saving the Trigger, returning
	#an error with the data if there is one
	def validate_and_save(self, request):
		self.description = request.get("user_desc", "")
		self.device_name = request.get("device_name", "")
		self.link_description = request.get("link_description", "")
		self.enabled = request.get("enable", "off") == "on"

		#Calling the submethod first ensures ALL trigger
		#properties are updated - even in case of invalid data
		val_err = self._validate_and_save(request)

		#Even if val_err is not empty, checking this gives the
		#impression the data is validated from top to bottom
		if self.description == "":
			val_err = "Please enter a short trigger description"

		if val_err == "":
			self.put()

		return val_err

	#Create a Trigger using the basic data, also calling the subclass to
	#save custom data from the request that's only used for that Trigger type
	@classmethod
	def create(cls, feedler, user_desc, device_name, request):
		link_desc = request.get("link_description", "")
		trigger = cls(parent=feedler.key, description=user_desc, device_name=device_name, link_description=link_desc)

		return trigger

	#Grab all the Trigger types and get their description to show to the user
	#when creating a new Trigger
	@classmethod
	def triggers_to_json(cls):
		triggers = {}
		subclasses = [NewArticleInStream, SavedForLater, NewArticleFromSearch]
		for TriggerCls in subclasses:
			triggers[TriggerCls.cls_id] = {
				"description": TriggerCls.cls_description,
				"model": TriggerCls
			}

		return triggers

	#Shortcut method to get a Trigger by base62 id
	@classmethod
	def get_by_base62(cls, feedler, trigger_id):
		num = from_base62(trigger_id)
		if num is -1:
			return None
		return ndb.Key(Trigger, num, parent=feedler.key).get()


#Check for new 'Saved For Later' articles
class SavedForLater(Trigger):
	cls_name = "Saved For Later"
	cls_id = "sfl"
	cls_description = "New Saved For Later article"
	
	#The user can unsave the article if they want to after the Trigger runs
	unsave = ndb.BooleanProperty('u', default=False, indexed=False)

	#The custom method to call the Feedly api for this Trigger
	def _run(self, newer_than):
		feedler = self.feedler
		feedly_api = feedler.feedly_api

		#Grab the saved for later list, only grabbing articles saved after the
		#last time this was ran
		saved_for_later_stream = feedler.get_global_saved()
		data = feedler.feedly_api.get_feed_content(saved_for_later_stream, False, newer_than)

		#Keep processing if articles were found
		item_len = 0 if "items" not in data else len(data["items"])
		if item_len > 0:

			article_ids = []
			rpcs = []

			#Loop through all of the articles
			for article in data["items"]:

				article_id = article["id"]
				title = self.get_link_description(article)
				article_url = get_article_url(article)

				#Make sure the article url was found
				if article_url == "":
					logging.error(article)
					continue

				#Linque the article to the Feedler's Linque account asynchronously
				litm_async = feedler.linque_it_to_me_async(article_url, title, self.device_name)
				rpcs.append(litm_async)

				article_ids.append(article_id)

			#If the user wants the articles unsaved, then unsave the aricles processed
			if self.unsave and len(article_ids) > 0:
				feedly_api.mark_article_unsaved(article_ids)

			#Make sure all Linque API calls are finished before ending
			if len(rpcs) > 0:
				for rpc in rpcs:
					rpc.wait()

		return data

	#This trigger processes custom data based on the request
	def _validate_and_save(self, request):
		self.unsave = request.get("unsave", "off") == "on"

		return ""

	#This Trigger doesn't have any custom parameters to pass to the reponse page
	@classmethod
	def customize_params(self, feedler, params):
		pass

#Check if there's a new article in a given stream
class NewArticleInStream(Trigger):
	cls_name = "Article in Stream"
	cls_id = "nais"
	cls_description = "New article in category, topic, tag or subscriptions"
	
	#Only search for unread articles
	only_unread = ndb.BooleanProperty('ou', default=True, indexed=False)
	
	#Allows the user to automatically mark the articles as read (so they don't see them in Feedly)
	mark_as_read = ndb.BooleanProperty('mar', default=False, indexed=False)

	#The category the user wants to track
	stream_id = ndb.StringProperty('si', required=True, indexed=False)

	@property
	def is_popular_source(self):
		return self.source == "topic/global.popular"

	#Custom run method for this Trigger type
	def _run(self, newer_than):
		feedler = self.feedler
		feedly_api = feedler.feedly_api

		is_popular = self.is_popular_source
		only_unread = self.only_unread if is_popular else False

		#Grab the articles from Feedly in the category
		data = feedler.feedly_api.get_feed_content(self.category_id, only_unread, newer_than)

		#Process the articles if some were found
		item_len = 0 if "items" not in data else len(data["items"])
		if item_len > 0:

			article_ids = []
			rpcs = []

			for article in data["items"]:

				article_id = article["id"]
				title = self.get_link_description(article)
				article_url = get_article_url(article)

				#Make sure the url was found
				if article_url == "":
					logging.error(article)
					continue

				#Linque the article to the Feedler's Linque account asynchronously
				litm_async = feedler.linque_it_to_me_async(article_url, title, self.device_name)
				rpcs.append(litm_async)

				article_ids.append(article_id)

			#Mark the articles as read/unsaved
			if not is_popular and self.mark_as_read and len(article_ids) > 0:
				feedly_api.mark_article_read(article_ids)

			#Since they were called asyncrounsly to save time,
			#make sure they all finished now
			if len(rpcs) > 0:
				for rpc in rpcs:
					rpc.wait()

		return data

	#Validate the custom data to this Trigger type
	def _validate_and_save(self, request):
		self.mark_as_read = request.get("mark_as_read", "off") == "on"
		self.only_unread = request.get("only_unread", "off") == "on"
		self.stream_id = request.get("source", "")

		if self.stream_id == "":
			return "Please select a Stream Source"

		return ""

	#This Trigger needs a list of categories in the Feedler's account
	@classmethod
	def customize_params(self, feedler, params):

		#All of the user's data is done asynchronously
		#instead of in serial to save page loading time

		subscriptions = feedler.all_subscriptions_async()
		categories = feedler.all_categories_async()
		tags = feedler.all_tags_async()
		topics = feedler.all_topics_async()

		#Don't show the Saved For Later global since another Trigger was
		#designed for that
		sfl_global = feedler.get_global_saved()
		global_streams = [g for g in feedler.all_globals() if g["id"] != sfl_global]
		logging.info(global_streams)

		sources = [["Globals", global_streams]]

		categories = categories.get_result()
		if len(categories) > 0:
			sources.append(["Categories", categories])
		tags = tags.get_result()
		if len(tags) > 0:
			sources.append(["Tags", tags])
		topics = topics.get_result()
		if len(topics) > 0:
			sources.append(["Topics", topics])
		subscriptions = subscriptions.get_result()
		if len(subscriptions) > 0:
			sources.append(["Subscriptions", subscriptions])

		params["sources"] = sources

#Find new articles based on a search
class NewArticleFromSearch(Trigger):
	cls_name = "New Article from Search"
	cls_id = "nafs"
	cls_description = "New article from search found in your Feedly"
	
	#The source is any category, global, feed, tag, etc the user can choose
	source = ndb.StringProperty('so', required=True, indexed=False)
	feedly_query = ndb.StringProperty('fq', required=True, indexed=False)

	#The fields allow the query to only search in certain places like the title, etc
	fields = ndb.StringProperty('f', repeated=True, indexed=False)

	#Optionally force embedded content, such as a video, to be in the article
	embedded = ndb.StringProperty('em', default="", indexed=False)
	#Optionally force the article to have medium or high engagement
	engagement = ndb.StringProperty('eg', default="", indexed=False)

	locale = ndb.StringProperty('eg', default="", indexed=False)

	#Check if the Feedler only wants to search through unread articles
	only_unread = ndb.BooleanProperty('ou', default=True, indexed=False)

	#Check if the user wants to mark the article as read
	mark_as_read = ndb.BooleanProperty('mar', default=False, indexed=False)

	@property
	def is_popular_source(self):
		return self.source == "topic/global.popular"

	#Run the Trigger to search for the articles
	def _run(self, newer_than):
		feedler = self.feedler
		feedly_api = feedler.feedly_api

		is_popular = self.is_popular_source

		#Don't filter by unread if searching globally
		#But DO filter by locale
		only_unread = self.only_unread if not is_popular else False
		locale = self.locale if is_popular else ""
		
		data = feedler.feedly_api.search_stream(self.source, self.feedly_query, newer_than,
			unread_only=only_unread, fields=self.fields, embedded=self.embedded,
			enagement=self.engagement, locale=locale)

		item_len = 0 if "items" not in data else len(data["items"])

		if item_len > 0:

			article_ids = []

			rpcs = []

			for article in data["items"]:

				article_id = article["id"]
				title = self.get_link_description(article)
				article_url = get_article_url(article)

				if article_url == "":
					logging.error(article)
					continue

				litm_async = feedler.linque_it_to_me_async(article_url, title, self.device_name)
				rpcs.append(litm_async)

				article_ids.append(article_id)

			#Don't mark read if searching popular
			if not is_popular and self.mark_as_read and len(article_ids) > 0:
				#If this is the Saved For Later stream, then we unsave them
				#vs mark them as read!
				if self.source != feedler.get_global_saved():
					feedly_api.mark_article_read(article_ids)
				else:
					feedly_api.mark_article_unsaved(article_ids)

			#Since they were called asyncrounsly to save time,
			#make sure they all finished now
			if len(rpcs) > 0:
				for rpc in rpcs:
					rpc.wait()

		return data

	#This Trigger type has a lot of custom data to validate and save
	def _validate_and_save(self, request):
		self.mark_as_read = request.get("mark_as_read", "off") == "on"
		self.only_unread = request.get("only_unread", "off") == "on"
		self.locale = request.get("locale", "")
		self.source = request.get("source", "")
		self.feedly_query = request.get("feedly_query", "")
		self.embedded = request.get("embedded", "")
		self.engagement = request.get("engagement", "")

		fields = []
		if request.get("field_title", "off") == "on":
			fields.append("title")
		if request.get("field_author", "off") == "on":
			fields.append("author")
		if request.get("field_keywords", "off") == "on":
			fields.append("keywords")

		#If they selected all or none, then they want all fields
		#to be used for matching
		if len(fields) in [1, 2]:
			self.fields = fields
		else:
			self.fields = []

		val_err = ""

		#Make sure all the data is valid, like embedded and engagement values
		if self.source == "":
			val_err = "Please select a source"
		elif  self.feedly_query == "":
			val_err = "Please enter a query (required)"
		elif self.embedded not in ["", "audio", "video", "any"]:
			val_err = "Invalid 'embedded' option"
		elif self.engagement not in ["", "medium", "high"]:
			val_err = "Invalid 'engagement' option"

		return val_err

	#Customize parameters to pass to the page
	@classmethod
	def customize_params(self, feedler, params):

		#All of the user's data is done asynchronously
		#instead of in serial to save page loading time

		subscriptions = feedler.all_subscriptions_async()
		categories = feedler.all_categories_async()
		tags = feedler.all_tags_async()
		topics = feedler.all_topics_async()

		sources = [["Globals", feedler.all_globals()]]

		categories = categories.get_result()
		if len(categories) > 0:
			sources.append(["Categories", categories])
		tags = tags.get_result()
		if len(tags) > 0:
			sources.append(["Tags", tags])
		topics = topics.get_result()
		if len(topics) > 0:
			sources.append(["Topics", topics])
		subscriptions = subscriptions.get_result()
		if len(subscriptions) > 0:
			sources.append(["Subscriptions", subscriptions])

		params["sources"] = sources