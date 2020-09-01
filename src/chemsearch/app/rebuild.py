import os
import logging
from threading import Thread

from flask import current_app

from . import db
from .models import Rebuild


def run_full_scan_and_rebuild(user=None, run_async=True):
    """Rescan and rebuild local archive. Requires app context."""
    if user is None or user.is_anonymous:
        r = Rebuild()
    else:
        r = Rebuild(user)
    db.session.add(r)
    db.session.commit()
    start_time = r.start_time.strftime('%Y-%m-%d %H:%M')
    r.set_status_and_commit(f"Rebuild started at {start_time}.")
    app = current_app._get_current_object()
    if run_async:
        thr = Thread(target=run_full_scan_and_rebuild_async, args=[app, r.id])
        thr.start()
        return thr
    else:
        run_full_scan_and_rebuild_async(app, r.id)


def run_full_scan_and_rebuild_async(app, build_id: str):
    from .. import _logger, drive
    from .. import admin
    from ..db import reload_molecules
    with app.app_context():
        archive_dir = current_app.config['LOCAL_DB_PATH']
        log_path = os.path.join(archive_dir, f'rebuild_{build_id}.log')
        fh = logging.FileHandler(log_path)
        fh.setLevel(logging.DEBUG)
        _logger.addHandler(fh)

        build = Rebuild.query.get(build_id)  # type: Rebuild
        if app.config['USE_DRIVE']:
            build.set_status_and_commit(
                "Identifying categories and MOL files in Drive.")
            meta = drive.Meta().build()
            build.set_status_and_commit("Updating local archive.")
            drive.create_local_archive(meta.molfiles, local_root=archive_dir,
                                       files_resource=meta.files_resource,
                                       scan_path=admin.SCAN_RESULTS_PATH)
        else:
            build.set_status_and_commit(
                "Identifying categories and MOL files in local archive.")
            admin.scan_local_archive()
        build.set_status_and_commit("Generating images and metadata.")
        df = admin.assemble_archive_metadata(archive_dir,
                                             use_drive=app.config['USE_DRIVE'])
        build.set_status_and_commit(f"Completed rebuild contains {len(df)} molecules.")
        build.mark_complete_and_commit()

        reload_molecules()
        _logger.removeHandler(fh)


def get_rebuilds_in_progress():
    return Rebuild.query.filter_by(complete=False)\
        .order_by(Rebuild.start_time).all()


def get_most_recent_complete_rebuild():
    return Rebuild.query.filter_by(complete=True)\
        .order_by(Rebuild.end_time.desc()).first()


def mark_rebuilds_as_failed(rebuild_list, commit=True):
    for rebuild in rebuild_list:
        rebuild.complete = None
        if commit:
            db.session.add(rebuild)
    if commit:
        db.session.commit()
