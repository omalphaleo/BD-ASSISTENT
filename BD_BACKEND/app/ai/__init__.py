"""AI package: provider-neutral adapter, Gemini and fake providers, NL search (M3-A6).

Needed so every model call goes through one place (ai-adapter rule). adapter.py is the interface
and error types, gemini.py the only SDK user, fake.py the test provider and nl_search.py the
sentence-to-filters task. Later milestones add drafting and reply classification here.
"""
