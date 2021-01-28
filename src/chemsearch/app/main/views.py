import logging
from datetime import datetime
from io import StringIO, BytesIO

from flask import render_template, flash, redirect, url_for, request, g, \
    current_app, abort, send_file
from flask_login import login_user, logout_user, current_user
from rdkit.Chem.rdmolfiles import SDWriter

from . import main
from .forms import admin_form_from_users, EmptyForm
from .. import db, META, filters, local
from ..decorators import membership_required, admin_required
from ..models import User, Rebuild
from ..oauth import OAuthSignIn
from ..paging import get_page_items_or_404, get_page_count
from ...db import get_substructure_matches, get_sim_matches, MolException, \
    LOCAL_MOLECULES, MOLECULE_DICT, DUPLICATE_TRACKER, valid_mols_present
from ... import drive


_logger = logging.getLogger(__name__)


@main.route('/', methods=['GET', 'POST'])
def index():
    if not current_app.config['USE_AUTH'] or not current_user.is_anonymous and current_user.in_team:
        pass_mols, filter_dict, sort_by = filters.sort_and_filter_mols(
            LOCAL_MOLECULES, request.args)
        filterable = filters.count_filterable(pass_mols)
        page_no = request.args.get('page', 1, type=int)
        molecules = get_page_items_or_404(pass_mols, page_no)
        n_pages = get_page_count(len(pass_mols))
        return render_template('index.html', molecules=molecules, n_pages=n_pages,
                               filters=filter_dict, filterable=filterable,
                               sort_by=sort_by)
    else:
        return render_template('index.html')


@main.route('/molecule/<inchi_key>', methods=['GET', 'POST'])
@membership_required
def molecule(inchi_key):
    mol = MOLECULE_DICT.get(inchi_key)
    if inchi_key in DUPLICATE_TRACKER.duplicated_inchi_keys:
        dup_ids = DUPLICATE_TRACKER.inchi_key_to_ids[inchi_key]
        names_str = ', '.join([f"<{i.category} - {i.mol_name}>" for i in dup_ids])
        flash(f"DUPLICATES FOUND: {names_str}", 'warning')
    if mol is None:
        abort(404, 'Molecule not found.')
    return render_template('molecule.html', mol=mol)


@main.route('/custom/<inchi_key>', methods=['POST'])
@membership_required
def custom_info(inchi_key):
    mol = MOLECULE_DICT.get(inchi_key)
    if mol is None:
        abort(404, 'Molecule not found.')
    if current_app.config['USE_DRIVE']:
        df, rec, content = drive.get_file_listing_and_custom_info(
            mol, files_resource=META.files_resource)
    else:
        df, rec, content = local.get_file_listing_and_custom_info(mol)
    custom_html = render_template('_custom.html', content=content, rec=rec)
    listing_html = render_template('_folder_files.html', df=df)
    return {'listing': listing_html, 'custom': custom_html}


@main.route('/build-status/', methods=['POST', 'GET'])
@admin_required
def build_status():
    build = Rebuild.get_most_recent_incomplete_rebuild()
    if build:
        is_complete = False
    else:
        build = Rebuild.get_most_recent_complete_rebuild()
        is_complete = True
    message = build.get_progress_message() if build else ''
    return {'status': message, 'is_complete': is_complete}


@main.route('/search', methods=['GET', 'POST'])
@membership_required
def search():
    return render_template('search.html')


@main.route('/results', methods=['GET'])
@membership_required
def results():
    """
    Request args:
        query: str
        query_type: ('smiles' (DEFAULT), 'smarts')
        search_type: in ('similarity', 'substructure')
    """
    pass_mols, filter_dict, sort_by = filters.sort_and_filter_mols(LOCAL_MOLECULES, request.args)
    query = request.args.get('query')
    query_type = request.args.get('query_type', 'smiles')
    is_smiles = query_type in ('smiles', '')
    search_type = request.args.get('search_type')
    if query in (None, '') or search_type in (None, ''):
        flash("Bad inputs", "error")
        return redirect(url_for('.search'))
    page_no = request.args.get('page', 1, type=int)
    molecules, molecules_all, sims, n_pages = None, None, None, None
    if search_type == 'substructure':
        try:
            molecules_all = get_substructure_matches(query, mols=pass_mols,
                                                     is_smarts=~is_smiles)
        except MolException as e:
            flash(str(e), "error")
            return redirect(url_for('.search'))
        n_pages = get_page_count(len(molecules_all))
        molecules = get_page_items_or_404(molecules_all, page_no) \
            if molecules_all else []
    elif search_type == 'similarity':
        if query_type == 'smarts':
            flash("Use SMILES rather than SMARTS for similarity search.", "error")
            return redirect(url_for('.search'))
        try:
            sims_all, molecules_all = get_sim_matches(query, mols=pass_mols)
        except MolException as e:
            flash(str(e), "error")
            return redirect(url_for('.search'))
        n_pages = get_page_count(len(molecules_all))
        molecules = get_page_items_or_404(molecules_all, page_no)
        sims = get_page_items_or_404(sims_all, page_no)
    else:
        abort(404, "Unrecognized search type.")
    filterable = filters.count_filterable(molecules_all)
    return render_template('results.html', query=query,
                           molecules=molecules, sims=sims,
                           search_type=search_type, n_pages=n_pages,
                           filters=filter_dict, filterable=filterable,
                           sort_by=sort_by, query_type=query_type,
                           )


@main.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin():
    if current_app.config['USE_AUTH'] and not current_user.is_admin:
        abort(503, 'Unauthorized')
    if current_app.config['USE_AUTH']:
        other_users = User.query.filter(User.id != current_user.id).all()
        form = admin_form_from_users(current_user, other_users)
        if form.validate_on_submit():
            updated_users = form.update_admins(other_users)
            flash(f'{len(updated_users)} admins modified.')
            return redirect(url_for('main.admin'))
    else:
        form = None
    last_rebuild = Rebuild.get_most_recent_complete_rebuild()
    in_progress_builds = Rebuild.get_rebuilds_in_progress()
    empty_form = EmptyForm()
    return render_template('admin.html', user_form=form,
                           empty_form=empty_form,
                           last_rebuild=last_rebuild,
                           in_progress_builds=in_progress_builds,)


@main.route('/sdf', methods=['GET'])
@admin_required
def sdf():
    if not valid_mols_present():
        flash("No valid MOL objects available for export.")
        return redirect(url_for('main.admin'))
    mimetype = 'chemical/x-mdl-sdfile'
    date_str = datetime.utcnow().strftime('%Y-%m-%d')
    filename = f'export_{date_str}.sdf'
    tmp_str = StringIO()
    sd_writer = SDWriter(tmp_str)
    for m in LOCAL_MOLECULES:
        if m.is_valid:
            sd_writer.write(m.mol)
    sd_writer.flush()
    tmp_str.seek(0)
    tmp_bytes = BytesIO()
    tmp_bytes.write(tmp_str.getvalue().encode('utf-8'))
    tmp_str.close()
    tmp_bytes.seek(0)
    return send_file(tmp_bytes, mimetype=mimetype, as_attachment=True,
                     attachment_filename=filename, cache_timeout=-1)


@main.route('/clear-rebuilds', methods=['POST'])
@admin_required
def clear_rebuilds():
    in_progress = Rebuild.get_rebuilds_in_progress()
    for r in in_progress:
        r.complete = None
        db.session.add(r)
    db.session.commit()
    flash("Incomplete rebuilds cleared.")
    return redirect(url_for('main.admin'))


@main.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('.index'))


@main.route('/reload', methods=['GET', 'POST'])
@admin_required
def reload():
    from ..rebuild import run_full_scan_and_rebuild
    run_full_scan_and_rebuild(current_user)
    return {'message': 'Rebuild in progress'}


@main.route('/authorize/<provider>')
def oauth_authorize(provider):
    if not current_user.is_anonymous:
        return redirect(url_for('.index'))
    oauth_obj = OAuthSignIn.get_provider(provider)
    return oauth_obj.authorize()


@main.route('/callback/<provider>')
def oauth_callback(provider):
    if not current_user.is_anonymous:
        return redirect(url_for('.index'))
    oauth_obj = OAuthSignIn.get_provider(provider)
    social_id, username, email, alt_email_str = oauth_obj.callback()
    if social_id is None:
        flash('Authentication failed.', 'error')
        return redirect(url_for('.index'))
    user = User.query.filter_by(social_id=social_id).first()
    modified = False
    # CREATE NEW USER IF NOT IN DB
    if not user:
        if social_id in g.members_dict:
            email = g.members_dict[social_id]
        user = User(social_id=social_id, display_name=username, email=email,
                    alt_email_str=alt_email_str)
        _logger.info(f"Creating new user: {email}.")
        modified = True
    # UPDATE EMAIL DATA IF NECESSARY
    if user.email != email or user.alt_email_str != alt_email_str:
        user.email = email
        user.alt_email_str = alt_email_str
        _logger.info(f"Modifying email for user: {email}.")
        modified = True
    if modified:
        db.session.add(user)
        db.session.commit()
    login_user(user, True)
    _logger.info(f"Logging in user: {email}.")
    return redirect(url_for('.index'))
