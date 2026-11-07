import sys

if len(sys.argv) > 1 and sys.argv[1] == "doctor":
    # standard-library only: must work even before `pip install -r requirements.txt`
    from promoforge.doctor import main as _doctor
    sys.exit(_doctor())

from promoforge.cli import main  # noqa: E402

sys.exit(main())
