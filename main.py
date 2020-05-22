from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.client.Extension import Extension
from ulauncher.api.shared.action.ActionList import ActionList
from ulauncher.api.shared.action.ExtensionCustomAction import ExtensionCustomAction
from ulauncher.api.shared.action.OpenUrlAction import OpenUrlAction
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.event import ItemEnterEvent, KeywordQueryEvent, PreferencesEvent, PreferencesUpdateEvent, SystemExitEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.utils.db.KeyValueDb import KeyValueDb

import logging
import re
import time

ERROR_ICON   = 'images/error_icon.png',
HISTORY_FILE = '/tmp/shit_goes_here.dat'
ZOOM_ICON    = 'images/zoom_icon.png'

logger = logging.getLogger(__name__)
shortcuts = {}

class ZoomJoinMeeting(Extension):
    def __init__(self):
        super(ZoomJoinMeeting, self).__init__()
        self.subscribe(ItemEnterEvent, LoadNewZoom())
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())
        self.subscribe(PreferencesEvent, PreferencesLoadListener())
        self.subscribe(PreferencesUpdateEvent, PreferencesUpdateListener())
        self.subscribe(SystemExitEvent, ShuttingDown())

class Shortcuts:
    __instance = None

    def __new__(cls):
        if cls.__instance is None:
            cls.__instance = object.__new__(cls)
            cls.__instance.data = {}

        return cls.__instance

    def update(self, shortcutString):
        self.data.clear
        logger.info("Updating Shortcuts - %s" % (shortcutString))
        shortcut_pairs = shortcutString
        for pair in shortcut_pairs.split(';'):
            key_value = pair.split(':')
            self.data[key_value[0]] = key_value[1]
            logger.debug("Shortcut %s for %s" % (key_value[0], key_value[1]))

class Zoom:
    def __init__(self, id, base_uri):
        self.base_uri = base_uri
        self.id = id
        self.type = ''

        # Fill out the object with extra data - order matters!!!
        self.check_for_shortcut()
        self.determine_link_type()

    def determine_link_type(self):
        logger.info("determine_link_type for %s" % (self.id))

        # Zoom offers two types of links:
        #  1) Meeting ID which is only numbers ('j')
        #  2) Personal Link which is 5-40 characters, start with a letter, and contain only a-z, 0-9, and '.' ('my')
        if re.match('^\d+$', self.id):
            self.type = 'j'
        elif re.match('^[a-z][a-z0-9.]{4,39}$', self.id):
            self.type = 'my'

        logger.info("Found that %s is %s" % (self.id, self.type))

    def check_for_shortcut(self):
        if self.id in shortcuts:
            logger.info("Shortcut found!  %s converted to %s" % (self.id, shortcuts[self.id]))
            self.id = shortcuts[self.id]

    def full_uri(self):
        return "https://" + self.base_uri + '/' + self.type + '/' + self.id

    def validate(self):
        logger.info("Validating Zoom ID: %s" % (self.id))
        if self.id and self.type:
            return True
        else:
            return False

class History:
    __instance = None

    def __new__(cls, max_matches = 5, enabled = "yes"):
        if cls.__instance is None:
            cls.__instance = object.__new__(cls)
            if (enabled == 'yes'):
                cls.__instance.enabled = True
            else:
                cls.__instance.enabled = False

            if int(max_matches) > 0:
                cls.__instance.max_matches = int(max_matches)
            else:
                logger.info("max_matches either not set or wasn't understood as an integer - falling back to default of 5")
                cls.__instance.max_matches = 5

            cls.__instance.history = {}

        return cls.__instance

    def load(self):
        logger.info("Loading data from file: %s" % (HISTORY_FILE))
        db = KeyValueDb(HISTORY_FILE).open()
        if len(db.get_records()):
            self.history = db.get_records()

    def save(self):
        logger.info("Saving History")
        db = KeyValueDb(HISTORY_FILE).open()
        db.set_records(self.history)
        db.commit()


    def get_matching(self, start):
        if not self.enabled:
            return []

        length_of_start = len(start)
        matching = []
        logger.info("Looking to match %s" % (start))
        matches_found = 0
        for id in self.history.keys():
            logger.info("Found ID: %s -- %s" % (id, id[:length_of_start]))
            if id[:length_of_start] == start:
                logger.info("Found match - adding %s" % (id))
                matches_found += 1
                matching.append(id)
                if matches_found >= self.max_matches:
                    break

        return matching

    def remember(self, id):
        logger.info("History may remember this!")
        if self.enabled:
            logger.info("Checking to see if we need to remember %s" % (id))
            current_epoch = int(time.time())
            data = self.history.get(id)

            if data:
                data['time'] = current_epoch
                data['count'] = data['count'] + 1
            else:
                data = { 'time': current_epoch, 'count': 1 }

            self.history[id] = data

class LoadNewZoom(EventListener):
    def on_event(self, event, extension):
        data = event.get_data()
        History().remember(data['id'])

class PreferencesLoadListener(EventListener):
    def on_event(self, event, extension):
        Shortcuts.update(event.preferences['shortcuts'])
        History(
            enabled     = event.preferences['history'],
            max_matches = event.preferences['history_count'],
        ).load()

class PreferencesUpdateListener(EventListener):
    def on_event(self, event, extension):
        if event.id == 'shortcuts':
            updateShortcuts(event.new_value)

class ShuttingDown(EventListener):
    def on_event(self, event, extension):
        History().save()

class KeywordQueryEventListener(EventListener):
    def on_event(self, event, extension):
        chat_id = event.get_query()[len(extension.preferences['zoom_kw']) + 1:]
        logger.info("User Input: %s" % (chat_id))

        zoom = None
        if chat_id:
            zoom = Zoom(id = chat_id, base_uri = extension.preferences['base_uri'])

        result_items = []
        if not zoom or not zoom.validate():
            result_items.append(ExtensionResultItem(
                icon = ERROR_ICON,
                name = 'Unable to verify Zoom ID: ' + chat_id
            ))
        else:
            result_items.append(ExtensionResultItem(
                icon = ZOOM_ICON,
                name = 'Open Zoom for: ' + zoom.full_uri(),
                on_enter = ActionList([
                    ExtensionCustomAction({ "id": zoom.id, "url": zoom.full_uri() }),
                    OpenUrlAction(zoom.full_uri())
                ])
            ))

            # We use chat_id instead of zoom.id here since chat_id what the user entered and not a shortcut
            history_items = History().get_matching(chat_id)
            for item in history_items:
                zoom = Zoom(id = item, base_uri = extension.preferences['base_uri'])
                result_items.append(ExtensionResultItem(
                    icon = ZOOM_ICON,
                    name = 'Open Zoom for: ' + zoom.full_uri(),
                    on_enter = OpenUrlAction(zoom.full_uri())
                ))

        return RenderResultListAction(result_items)

if __name__ == '__main__':
    ZoomJoinMeeting().run()