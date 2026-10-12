"""
URL configuration for gitgrit project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

from oauth2_provider import views as oauth2_views

urlpatterns = [
    # /up/ is handled by HealthCheckMiddleware (before ALLOWED_HOSTS)
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("", include("app.presentation.web_urls")),
    path("api/v1/", include("app.presentation.api.urls")),
    path("api/", include("app.urls")),
    # OAuth 2.0 (django-oauth-toolkit): only the endpoints the CLI uses.
    # DOT's application-management views are deliberately not mounted —
    # clients are registered by migration, not by users.
    path(
        "oauth/",
        include(
            (
                [
                    path("authorize/", oauth2_views.AuthorizationView.as_view(), name="authorize"),
                    path("token/", oauth2_views.TokenView.as_view(), name="token"),
                    path("revoke_token/", oauth2_views.RevokeTokenView.as_view(), name="revoke-token"),
                ],
                "oauth2_provider",
            )
        ),
    ),
    path(
        ".well-known/oauth-authorization-server",
        oauth2_views.OAuthServerMetadataView.as_view(),
        name="oauth-server-metadata",
    ),
]
