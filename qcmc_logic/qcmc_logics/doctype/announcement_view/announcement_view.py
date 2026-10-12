from hashlib import sha256
import json

from frappe.model.document import Document


class AnnouncementView(Document):
    def autoname(self):
        # The primary key enforces one view per announcement/user even when
        # multiple browser tabs submit the first view at the same time.
        self.name = sha256(json.dumps([self.announcement, self.viewer]).encode()).hexdigest()
