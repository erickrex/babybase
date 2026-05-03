"""Pagination classes for BabyBase API."""

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    """Standard page-number pagination with configurable page size.

    Default page size: 20
    Max page size: 100
    Query param: ?page_size=N
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        """Return paginated response with status field and pagination metadata."""
        # If data is a dict with 'status' and 'data' keys, extract and wrap
        if isinstance(data, dict) and "data" in data:
            return Response({
                "status": data.get("status", "success"),
                "data": data["data"],
                "count": self.page.paginator.count,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
            })

        # Default: wrap raw data
        return Response({
            "status": "success",
            "data": data,
            "count": self.page.paginator.count,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
        })
