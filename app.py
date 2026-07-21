import io
import os
from datetime import datetime

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from flask import Flask, flash, redirect, render_template, request, send_file, url_for
from flask_sqlalchemy import SQLAlchemy

from extract import extract_from_pdf

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'akulab-dev-key-change-in-prod')

db_url = os.environ.get('DATABASE_URL', 'sqlite:///protokoly.db')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024

db = SQLAlchemy(app)


class Protocol(db.Model):
    __tablename__ = 'protocols'

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(100), unique=True, nullable=False)
    client = db.Column(db.String(500))
    measurement_date = db.Column(db.Date)
    issue_date = db.Column(db.Date)
    auth_set = db.Column(db.String(20))
    year = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def fmt_date(self, d):
        return d.strftime('%-d. %-m. %Y') if d else '—'

    @property
    def measurement_date_str(self):
        return self.fmt_date(self.measurement_date)

    @property
    def issue_date_str(self):
        return self.fmt_date(self.issue_date)


with app.app_context():
    db.create_all()


def _apply_filters(query):
    rok = request.args.get('rok', '').strip()
    auth_set = request.args.get('set', '').strip()
    search = request.args.get('search', '').strip()
    if rok:
        query = query.filter(Protocol.year == int(rok))
    if auth_set:
        query = query.filter(Protocol.auth_set == auth_set)
    if search:
        like = f'%{search}%'
        query = query.filter(
            db.or_(Protocol.number.ilike(like), Protocol.client.ilike(like))
        )
    return query


@app.route('/')
def index():
    query = _apply_filters(Protocol.query)
    protocols = query.order_by(Protocol.issue_date.desc()).all()

    all_years = [r[0] for r in db.session.query(Protocol.year)
                 .distinct().order_by(Protocol.year.desc()).all() if r[0]]
    all_sets = [r[0] for r in db.session.query(Protocol.auth_set)
                .distinct().order_by(Protocol.auth_set).all() if r[0]]

    return render_template('index.html',
        protocols=protocols,
        all_years=all_years,
        all_sets=all_sets,
        current_rok=request.args.get('rok', ''),
        current_set=request.args.get('set', ''),
        current_search=request.args.get('search', ''),
        total=Protocol.query.count(),
    )


@app.route('/upload', methods=['POST'])
def upload():
    file = request.files.get('pdf')
    if not file or not file.filename.lower().endswith('.pdf'):
        flash('Vyber soubor ve formátu PDF.', 'danger')
        return redirect(url_for('index'))

    try:
        data = extract_from_pdf(file.stream)
    except Exception as e:
        flash(f'Chyba při čtení PDF: {e}', 'danger')
        return redirect(url_for('index'))

    if not data.get('number'):
        flash('Nepodařilo se načíst číslo protokolu. Zkontroluj formát souboru.', 'danger')
        return redirect(url_for('index'))

    if Protocol.query.filter_by(number=data['number']).first():
        flash(f'Protokol {data["number"]} již v databázi existuje.', 'warning')
        return redirect(url_for('index'))

    p = Protocol(
        number=data['number'],
        client=data.get('client'),
        measurement_date=data.get('measurement_date'),
        issue_date=data.get('issue_date'),
        auth_set=data.get('auth_set'),
        year=data['issue_date'].year if data.get('issue_date') else None,
    )
    db.session.add(p)
    db.session.commit()
    flash(f'Protokol {p.number} byl úspěšně přidán.', 'success')
    return redirect(url_for('index'))


@app.route('/delete/<int:id>', methods=['POST'])
def delete(id):
    p = db.get_or_404(Protocol, id)
    number = p.number
    db.session.delete(p)
    db.session.commit()
    flash(f'Protokol {number} byl smazán.', 'success')
    return redirect(url_for('index'))


@app.route('/export')
def export():
    query = _apply_filters(Protocol.query)
    protocols = query.order_by(Protocol.issue_date.desc()).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Protokoly'

    HDR_FILL = PatternFill('solid', fgColor='1F4E79')
    HDR_FONT = Font(color='FFFFFF', bold=True)
    ALT_FILL = PatternFill('solid', fgColor='D9E2F3')
    CENTER = Alignment(horizontal='center', vertical='center')

    headers = ['Číslo protokolu', 'Objednatel', 'Datum měření', 'Datum vydání', 'Set', 'Rok']
    widths = [24, 45, 16, 16, 8, 8]

    for col, (h, w) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = HDR_FILL
        cell.font = HDR_FONT
        cell.alignment = CENTER
        ws.column_dimensions[cell.column_letter].width = w

    for row, p in enumerate(protocols, 2):
        values = [p.number, p.client or '—', p.measurement_date_str,
                  p.issue_date_str, p.auth_set or '—', p.year or '—']
        for col, v in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=v)
            cell.alignment = Alignment(vertical='center')
            if row % 2 == 0:
                cell.fill = ALT_FILL

    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = f'A1:F{len(protocols) + 1}'

    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)

    rok = request.args.get('rok', '')
    s = request.args.get('set', '')
    fname = f'protokoly{"_" + rok if rok else ""}{"_" + s if s else ""}.xlsx'
    return send_file(stream, as_attachment=True, download_name=fname,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


if __name__ == '__main__':
    app.run(debug=True)
