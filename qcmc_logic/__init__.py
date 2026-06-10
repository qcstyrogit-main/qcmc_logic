__version__ = "0.0.1"


def _patch_meta_init():
    """
    Frappe v16 / Python 3.14: Meta.__init__ calls self.process() but init_valid_columns()
    sets self.__dict__['process'] = None when the 'process' fieldname appears in
    get_valid_columns(), shadowing the class method. Delete the instance attribute
    before the call so the class method is always reachable.
    """
    from frappe.model.meta import Meta
    from frappe.model.document import Document

    _original_init = Meta.__init__

    def _safe_init(self, doctype):
        if isinstance(doctype, Document):
            super(Meta, self).__init__(doctype.as_dict())
        else:
            super(Meta, self).__init__("DocType", doctype)
        # Remove any instance attribute named 'process' set by init_valid_columns
        # so the class method Meta.process is always callable.
        self.__dict__.pop("process", None)
        self.process()

    Meta.__init__ = _safe_init


_patch_meta_init()
