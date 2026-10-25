class ClinicalAIError(Exception):
    """Public errors are fixed strings, never upstream errors or clinical content."""
    def __init__(self, status_code, public_message, category):
        super().__init__(public_message)
        self.status_code = status_code
        self.public_message = public_message
        self.category = category
