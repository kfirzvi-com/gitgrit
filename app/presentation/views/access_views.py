"""Getting in: first-run setup, a pending person's request page, and the
superuser review queue. The rules live in ``app.application.access``."""
from allauth.account import signals as account_signals
from allauth.account.utils import filter_users_by_email
from allauth.account.views import LoginView
from allauth.core import ratelimit
from django import forms
from django.contrib import messages
from django.contrib.auth import login, password_validation
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect, render

from app.application.access import (
    SetupAlreadyDone,
    create_first_admin,
    register_with_password,
    onboarding_form_required,
    setup_required,
    setup_token_matches,
    submit_access_request,
)
from app.domain.models import AccessRequest, Tenant
from app.presentation.auth_adapters import PENDING_USER_SESSION_KEY


# --- first-run setup -------------------------------------------------------


class FirstRunSetupForm(forms.Form):
    token = forms.CharField(max_length=128)
    email = forms.EmailField(max_length=254)
    password1 = forms.CharField(widget=forms.PasswordInput)
    password2 = forms.CharField(widget=forms.PasswordInput)

    def clean_token(self):
        token = self.cleaned_data["token"]
        if not setup_token_matches(token):
            raise ValidationError(
                "That token doesn't match. Copy it from the app log or run "
                "`manage.py setup_token`."
            )
        return token

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The passwords don't match.")
        elif p1:
            try:
                password_validation.validate_password(p1)
            except ValidationError as e:
                self.add_error("password1", e)
        return data


def first_run_setup(request):
    if not setup_required():
        raise Http404()

    if request.method == "POST":
        form = FirstRunSetupForm(request.POST)
        if form.is_valid():
            try:
                user = create_first_admin(
                    form.cleaned_data["email"], form.cleaned_data["password1"]
                )
            except SetupAlreadyDone:
                raise Http404()
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(
                request, "You're the admin. Create the first workspace to get going."
            )
            return redirect("create_tenant")
    else:
        form = FirstRunSetupForm(initial={"token": request.GET.get("token", "")})

    return render(request, "pages/first_run_setup.html", {"form": form})


# --- sign in, or sign up with an unknown email ----------------------------


class EmailPasswordForm(forms.Form):
    """Carries errors back to the sign-in box when the signup path refuses;
    field names match allauth's login form so one template renders both."""

    login = forms.EmailField(max_length=254)
    password = forms.CharField()


class EmailAwareLoginView(LoginView):
    """allauth's login, plus: an email nobody has signed up with signs up.

    A known email goes through allauth unchanged (rate limits, the inactive
    redirect to a pending person's request page, "incorrect password"). An
    account that only ever signed in through a provider has no password to
    check, so it is told which way in it uses instead of "incorrect".
    """

    def post(self, request, *args, **kwargs):
        email = (request.POST.get("login") or "").strip()
        password = request.POST.get("password") or ""
        if not email or not password:
            return super().post(request, *args, **kwargs)

        users = filter_users_by_email(email)
        if not users:
            return self._sign_up(request, email, password)
        if not any(user.has_usable_password() for user in users):
            return self._refuse(
                "This account signs in with a provider. Use the button above "
                "you signed up with."
            )
        return super().post(request, *args, **kwargs)

    def _sign_up(self, request, email, password):
        limited = ratelimit.consume_or_429(request, action="signup")
        if limited:
            return limited
        form = EmailPasswordForm(request.POST)
        if not form.is_valid():
            return self._render(form)
        email = form.cleaned_data["login"]
        try:
            password_validation.validate_password(password)
        except ValidationError as e:
            form.add_error(None, " ".join(e.messages))
            return self._render(form)

        user = register_with_password(email, password)
        account_signals.user_signed_up.send(
            sender=user.__class__, request=request, user=user
        )
        if not user.is_active:
            request.session[PENDING_USER_SESSION_KEY] = str(user.pk)
            return redirect("access_request_status")
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "Welcome to GitGrit.")
        return redirect("dashboard")

    def _refuse(self, message):
        form = EmailPasswordForm(self.request.POST)
        form.is_valid()
        form.add_error(None, message)
        return self._render(form)

    def _render(self, form):
        return self.render_to_response(self.get_context_data(form=form))


# --- the pending person's page --------------------------------------------


class AccessRequestForm(forms.Form):
    name = forms.CharField(max_length=200)
    company = forms.CharField(max_length=200)
    role = forms.CharField(max_length=200)
    goals = forms.CharField(max_length=2000, widget=forms.Textarea)


def access_request_status(request):
    """Where a gated signup lands, and lands again on every later sign-in
    until approved. Not behind login: the person is inactive and cannot be
    logged in. allauth's inactive hook names them in the session."""
    user_id = request.session.get(PENDING_USER_SESSION_KEY)
    access_request = (
        AccessRequest.objects.select_related("user").filter(user_id=user_id).first()
        if user_id
        else None
    )
    if access_request is None:
        return redirect("account_login")

    needs_form = (
        access_request.is_pending
        and onboarding_form_required()
        and not access_request.is_submitted
    )
    form = None
    if needs_form:
        if request.method == "POST":
            form = AccessRequestForm(request.POST)
            if form.is_valid():
                submit_access_request(access_request, form.cleaned_data)
                return redirect("access_request_status")
        else:
            form = AccessRequestForm()

    return render(
        request,
        "pages/access_request_status.html",
        {"access_request": access_request, "form": form},
    )


# --- signed in, but in no workspace ---------------------------------------


@login_required
def no_workspace(request):
    if request.tenant is not None:
        return redirect("dashboard")
    workspaces = Tenant.objects.order_by("name") if request.user.is_superuser else []
    return render(request, "pages/no_workspace.html", {"workspaces": workspaces})
