"""Pagination for plain Python lists.

Flask-SQLAlchemy's ``Query.paginate()`` only works on a single query. The
admin "Users" view combines rows from four different tables (donors,
patients, hospitals, admins) into one Python list first, so it needs its
own lightweight paginator with the same ``.items`` / ``.page`` / ``.pages``
shape the existing ``pagination`` template macro already expects.
"""


class SimplePagination:
    """Minimal stand-in for a Flask-SQLAlchemy Pagination object."""

    def __init__(self, items, page, per_page, total):
        self.page = page
        self.per_page = per_page
        self.total = total
        self.pages = max(1, (total + per_page - 1) // per_page)
        start = (page - 1) * per_page
        self.items = items[start:start + per_page]
        self.has_prev = page > 1
        self.has_next = page < self.pages
        self.prev_num = page - 1
        self.next_num = page + 1


def paginate_list(items, page, per_page):
    page = max(1, page)
    return SimplePagination(items, page, per_page, len(items))
