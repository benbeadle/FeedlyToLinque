
def feedler_triggers(feedler_key):
	from models.Trigger import Trigger
	
	triggers = Trigger.query(ancestor=feedler_key).fetch()

	#Return the Triggers sorted by the time they were created
	return sorted(triggers, key=lambda trigger: trigger.created, reverse=True)

#Return the Triggers that haven't run since max_datetime
def trigger_to_run(max_datetime, limit=None):
	from models.Trigger import Trigger

	query = Trigger.query().filter(Trigger.last_run <= max_datetime)
	query = query.filter(Trigger.enabled == True)

	return query.fetch(limit=limit)