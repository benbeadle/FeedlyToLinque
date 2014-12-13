

def feedler_triggers(feedler_key):
	from models.Trigger import Trigger
	
	triggers = Trigger.query(ancestor=feedler_key).fetch()

	#Return the Triggers sorted by the time they were created
	return sorted(triggers, key=lambda trigger: trigger.created, reverse=True)