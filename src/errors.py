"""Stable, coded failures. Messages are safe to show a user: no paths, no secrets."""


class BardError(Exception):
    code = "bard_error"


class TextRejected(BardError):
    code = "text_rejected"


class QuotaExceeded(BardError):
    code = "quota_exceeded"


class VoiceUnavailable(BardError):
    code = "voice_unavailable"


class EngineFailed(BardError):
    code = "engine_failed"


class IdentityRequired(BardError):
    code = "identity_required"


class AdminRequired(BardError):
    code = "admin_required"


class CatalogUnavailable(BardError):
    code = "catalog_unavailable"


class VoiceNotInCatalog(BardError):
    code = "voice_not_in_catalog"


class VoiceAlreadyInstalled(BardError):
    code = "voice_already_installed"


class DownloadFailed(BardError):
    code = "download_failed"
