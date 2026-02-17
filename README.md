# DICOM Structure Comparison System

A Django-based web application for comparing and evaluating RT structure sets with advanced DICOM visualization tools.

## Features

- 📁 **Patient Management** - Browse and manage patient DICOM studies
- 🔍 **DICOM Viewer** - Advanced side-by-side CT and RTSTRUCT visualization
- 📊 **Structure Comparison** - Compare manual vs automatic RT structure sets
- 🎨 **Interactive ROI Overlays** - Toggle and visualize multiple ROI contours
- ⚙️ **Window/Level Controls** - Adjust CT image display with presets
- 🔄 **Slice Navigation** - Navigate through CT slices with keyboard shortcuts

## Technology Stack

- **Backend:** Django 5.0+
- **Frontend:** HTML, CSS (TailwindCSS), Vanilla JavaScript
- **DICOM Processing:** pydicom, NumPy
- **Database:** SQLite (development), PostgreSQL (production ready)

## Installation

### Prerequisites

- Python 3.10 or higher
- pip (Python package manager)

### Setup

1. **Clone the repository:**
```bash
git clone <repository-url>
cd Structure-Comparision
```

2. **Create a virtual environment:**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies:**
```bash
pip install -r requirements.txt
```

4. **Run migrations:**
```bash
python manage.py migrate
```

5. **Create a superuser (for admin access):**
```bash
python manage.py createsuperuser
```

6. **Run the development server:**
```bash
python manage.py runserver 8014
```

7. **Access the application:**
- Home: http://localhost:8014/
- Patient List: http://localhost:8014/patients/
- Admin Panel: http://localhost:8014/admin/

## Importing DICOM Files

### Method 1: Using the populate script (Recommended)

```bash
python populate_dicom_database.py /path/to/dicom/directory
```

### Method 2: Using Django management command

```bash
python manage.py import_dicom_directory /path/to/dicom/directory
```

### Expected Directory Structure

```
dicom/
├── patient_id_1/
│   ├── CT_slice_001.dcm
│   ├── CT_slice_002.dcm
│   ├── ...
│   ├── RTSTRUCT_manual.dcm
│   └── RTSTRUCT_auto.dcm
└── patient_id_2/
    └── ...
```

## Project Structure

```
Structure-Comparision/
├── rtstructcompare/          # Main Django app
│   ├── models.py            # Database models
│   ├── views.py             # View functions (cleaned)
│   ├── urls.py              # URL routing
│   ├── admin.py             # Admin configuration
│   └── management/          # Custom management commands
├── templates/               # HTML templates
│   ├── base.html           # Base template
│   ├── home.html           # Landing page
│   ├── patients.html       # Patient list
│   └── dicom_web_viewer.html  # DICOM viewer
├── static/                  # Static files (CSS, JS, images)
├── dicom/                   # DICOM files directory (gitignored)
├── populate_dicom_database.py  # DICOM import script
├── requirements.txt         # Python dependencies
└── manage.py               # Django management script
```

## Database Models

### Patient
- `patient_id` - Unique patient identifier
- `patient_name` - Patient name
- `patient_birth_date` - Date of birth
- `patient_sex` - Gender

### DICOMStudy
- Links to Patient
- `study_instance_uid` - Unique study identifier
- `study_date` - Study date
- `study_description` - Study description

### DICOMSeries
- Links to DICOMStudy
- `series_instance_uid` - Unique series identifier
- `modality` - CT, RTSTRUCT, etc.
- `series_description` - Series description
- `series_root_path` - Path to DICOM files

### DICOMInstance
- Links to DICOMSeries
- `sop_instance_uid` - Unique instance identifier
- `instance_number` - Instance number
- `instance_path` - Full path to DICOM file

## Usage

### Viewing Patients

1. Navigate to http://localhost:8014/patients/
2. Browse the list of imported patients
3. Click "Compare Studies" to open the DICOM viewer

### DICOM Viewer Controls

**Navigation:**
- Previous/Next buttons - Navigate between slices
- Slice slider - Jump to specific slice
- Arrow Up/Down keys - Navigate slices

**Window/Level:**
- Soft Tissue - W:400, L:40
- Lung - W:1500, L:-600
- Bone - W:2000, L:300
- Brain - W:80, L:40
- Liver - W:150, L:60
- Custom - Manual adjustment

**ROI Overlays:**
- Select individual ROIs from the list
- Select All / Clear All buttons
- Common structures shown between both RTSTRUCT files

## Development

### Running Tests

```bash
python manage.py test
```

### Checking for Issues

```bash
python manage.py check
```

### Creating Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

## Configuration

### Settings

Key settings in `rtstructcompare/settings.py`:

- `DEBUG` - Set to `False` in production
- `ALLOWED_HOSTS` - Add your domain in production
- `DATABASES` - Configure PostgreSQL for production
- `STATIC_ROOT` - Set for production static files

### Environment Variables

Create a `.env` file for sensitive settings:

```env
SECRET_KEY=your-secret-key-here
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
DATABASE_URL=postgresql://user:password@localhost/dbname
```

## Deployment

### Production Checklist

- [ ] Set `DEBUG = False`
- [ ] Configure `ALLOWED_HOSTS`
- [ ] Use PostgreSQL database
- [ ] Set up static file serving
- [ ] Configure HTTPS
- [ ] Set strong `SECRET_KEY`
- [ ] Enable CSRF protection
- [ ] Configure logging
- [ ] Set up backups

### Static Files

```bash
python manage.py collectstatic
```

## Troubleshooting

### DICOM Import Issues

**Problem:** Files not importing
- Check file permissions
- Verify DICOM file format
- Check console output for errors

**Problem:** Missing RTSTRUCT files
- Ensure at least 2 RTSTRUCT files per patient
- Check modality field in DICOM files

### Viewer Issues

**Problem:** Blank/black canvases
- Check browser console for JavaScript errors
- Verify CT and RTSTRUCT data loaded correctly
- Check that pixel data exists in DICOM files

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

[Add your license here]

## Support

For issues and questions:
- Create an issue on GitHub
- Contact: [your-email@example.com]

## Acknowledgments

- Built with Django
- DICOM processing powered by pydicom
- UI components using TailwindCSS

---

**Version:** 1.0.0  
**Last Updated:** January 2026
