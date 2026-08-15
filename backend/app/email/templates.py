from html import escape

from app.email.provider import EmailMessage

_PRODUCT = "Enterprise Knowledge Hub"

# Everything interpolated into the HTML half is escaped. `workspace_name` is
# chosen by whoever signed up and lands in someone else's inbox, so it is
# attacker-controlled in a self-serve product. `link` is server-built but is
# escaped too -- an unescaped value inside an href attribute is a habit worth
# not forming. Plain-text halves are never escaped: entities would render
# literally there.


def verify_email_message(to: str, link: str) -> EmailMessage:
    safe_link = escape(link)
    text = (
        f"Welcome to {_PRODUCT}.\n\n"
        f"Confirm this address to activate your workspace:\n{link}\n\n"
        "This link expires in 7 days. If you didn't sign up, ignore this email."
    )
    body = (
        f"<p>Welcome to {_PRODUCT}.</p>"
        f'<p><a href="{safe_link}">Confirm your email address</a></p>'
        f"<p>Or paste this link: {safe_link}</p>"
        "<p>This link expires in 7 days. If you didn't sign up, ignore this email.</p>"
    )
    return EmailMessage(to=to, subject=f"Confirm your {_PRODUCT} email", text=text, html=body)


def password_reset_message(to: str, link: str) -> EmailMessage:
    safe_link = escape(link)
    text = (
        f"A password reset was requested for your {_PRODUCT} account.\n\n"
        f"Reset it here:\n{link}\n\n"
        "This link expires in 1 hour. If you didn't request it, ignore this email."
    )
    body = (
        f"<p>A password reset was requested for your {_PRODUCT} account.</p>"
        f'<p><a href="{safe_link}">Reset your password</a></p>'
        f"<p>Or paste this link: {safe_link}</p>"
        "<p>This link expires in 1 hour. If you didn't request it, ignore this email.</p>"
    )
    return EmailMessage(to=to, subject=f"Reset your {_PRODUCT} password", text=text, html=body)


def invite_message(to: str, workspace_name: str, inviter_email: str, link: str) -> EmailMessage:
    safe_link = escape(link)
    safe_workspace = escape(workspace_name)
    safe_inviter = escape(inviter_email)
    text = (
        f"{inviter_email} invited you to the {workspace_name} workspace "
        f"on {_PRODUCT}.\n\nAccept the invitation:\n{link}\n\n"
        "This invitation expires in 7 days."
    )
    body = (
        f"<p>{safe_inviter} invited you to the <strong>{safe_workspace}</strong> "
        f"workspace on {_PRODUCT}.</p>"
        f'<p><a href="{safe_link}">Accept the invitation</a></p>'
        f"<p>Or paste this link: {safe_link}</p>"
        "<p>This invitation expires in 7 days.</p>"
    )
    return EmailMessage(to=to, subject=f"Join {workspace_name} on {_PRODUCT}", text=text, html=body)
