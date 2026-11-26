from django.conf import settings
from django.shortcuts import render
from django_otp.decorators import otp_required

from . import search as document_search
from . import storage
from .models import Document


@otp_required
def documents(request):
    """`/documents/`: one query, the same snippets the WhatsApp tool gets (§10)."""
    query = request.GET.get("q", "").strip()
    results = document_search.search(query) if query else []
    listing = (
        []
        if query
        else Document.objects.filter(is_active=True).select_related("case")[:50]
    )
    return render(
        request,
        "docs/documents.html",
        {
            "query": query,
            "results": results,
            "documents": listing,
            "cap_warning": storage.cap_warning(),
            "cap_percent": round(storage.cap_ratio() * 100),
            "instance_name": settings.CONFIG["name"],
        },
    )
