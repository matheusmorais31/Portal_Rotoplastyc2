def __init__(self, *args, **kwargs):
    bi_report = kwargs.pop('bi_report', None)
    super().__init__(*args, **kwargs)
    if bi_report:
        self.fields['roles'].queryset = bi_report.allowed_roles.all()
