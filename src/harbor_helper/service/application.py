"""Compose HTTP-facing application capabilities over one persistent service store."""

from harbor_helper.execution.config import load_team
from harbor_helper.service.admission import readiness
from harbor_helper.service.attachments import Attachments
from harbor_helper.service.bundles import Bundles
from harbor_helper.service.cancellation import Cancellation
from harbor_helper.service.configuration import TeamConfiguration
from harbor_helper.service.data import ServiceData
from harbor_helper.service.evidence import Evidence
from harbor_helper.service.submissions import Submissions


class Application(Submissions, Cancellation, Evidence):
    def __init__(self, root):
        self.data = ServiceData(root)
        self.store = self.data.store
        self.configuration = TeamConfiguration(self.data)

        self.attachments = Attachments(self.data, Bundles(self.data))

    def catalog(self, user_id=None):
        settings = self.configuration.settings()
        default_dataset = load_team(self.store)["dataset"]
        if settings.get("default_dataset_id"):
            selected = self.data.object("dataset", settings["default_dataset_id"])
            default_dataset = selected["reference"]
        return {
            **self.configuration.catalog(),
            **self.attachments.catalog(),
            "providers": self.data.objects("provider"),
            "credentials": self.data.credentials(),
            "model_profiles": self.data.objects("profile"),
            "limits": self.data.limits(),
            "default_dataset": default_dataset,
            "readiness": readiness(self, user_id),
        }
