"""External dependencies. Here they are simulated, so failures can be scripted for demos and tests.

To connect a real service, write another class with a check(request_id, data) method
that returns a dict, or raises DependencyError. The engine does not care what is behind it.
"""

# Scripted responses for specific applicants. Anyone else gets DEFAULT_SCORE.
DEFAULT_SCORES = {"APP-2002": 600}   # 600 is below the 650 minimum, so this applicant goes to manual review
DEFAULT_SCORE = 720


class DependencyError(Exception):
    """The dependency could not answer. The engine decides whether to retry."""


class CreditBureauSimulator:
    name = "credit_bureau"

    def __init__(self, fail_next=0, scores=None, default_score=DEFAULT_SCORE):
        self.fail_next = fail_next       # the next N calls raise DependencyError
        self.scores = dict(scores or {})
        self.default_score = default_score
        self.calls = 0                   # how many times the engine actually called us

    def check(self, request_id, data):
        self.calls += 1
        if self.fail_next > 0:
            self.fail_next -= 1
            raise DependencyError("credit bureau timed out (simulated)")
        applicant = data.get("applicant_id")
        return {
            "credit_score": self.scores.get(applicant, self.default_score),
            "bureau_ref": f"CB-{request_id[-6:]}",
        }
