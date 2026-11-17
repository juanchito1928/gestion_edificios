from rest_framework.pagination import CursorPagination


class IncidenciaCursorPagination(CursorPagination):
    page_size = 25
    ordering = '-fecha_creacion'
    cursor_query_param = 'cursor'