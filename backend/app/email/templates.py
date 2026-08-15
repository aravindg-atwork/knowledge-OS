from app.email.provider import EmailMessage

_PRODUCT = "Enterprise Knowledge Hub"


def verify_email_message(to: str, link: str) -> EmailMessage:
    text = (
        f"Welcome to {_PRODUCT}.\n\n"
        f"Confirm this address to activate your workspace:\n{link}\n\n"
        "This link expires in 7 days. If you didn't sign up, ignore this email."
    )
    html = (
        f"<p>Welcome to {_PRODUCT}.</p>"
        f'<p><a href="{link}">Confirm your email address</a></p>'
        f"<p>Or paste this link: {link}</p>"
        "<p>This link expires in 7 days. If you didn't sign up, ignore this email.</p>"
    )
    return EmailMessage(to=to, subject=f"Confirm your {_PRODUCT} email", text=text, html=html)


def password_reset_message(to: str, link: str) -> EmailMessage:
    text = (
        f"A password reset was requested for your {_PRODUCT} account.\n\n"
        f"Reset it here:\n{link}\n\n"
        "This link expires in 1 hour. If you didn't request it, ignore this email."
    )
    html = (
        f"<p>A password reset was requested for your {_PRODUCT} account.</p>"
        f'<p><a href="{link}">Reset your password</a></p>'
        f"<p>Or paste this link: {link}</p>"
        "<p>This link expires in 1 hour. If you didn't request it, ignore this email.</p>"
    )
    return EmailMessage(to=to, subject=f"Reset your {_PRODUCT} password", text=text, html=html)


def invite_message(to: str, workspace_name: str, inviter_email: str, link: str) -> EmailMessage:
    text = (
        f"{inviter_email} invited you to the {workspace_name} workspace "
        f"on {_PRODUCT}.\n\nAccept the invitation:\n{link}\n\n"
        "This invitation expires in 7 days."
    )
    html = (
        f"<p>{inviter_email} invited you to the <strong>{workspace_name}</strong> "
        f"workspace on {_PRODUCT}.</p>"
        f'<p><a href="{link}">Accept the invitation</a></p>'
        f"<p>Or paste this link: {link}</p>"
        "<p>This invitation expires in 7 days.</p>"
    )
    return EmailMessage(to=to, subject=f"Join {workspace_name} on {_PRODUCT}", text=text, html=html)
