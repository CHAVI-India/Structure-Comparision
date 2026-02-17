"""
Utility functions for rendering CT images with RT Structure overlays using matplotlib
"""
import pydicom
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
import io
import base64


def load_ct_slice(dicom_path, slice_index=0):
    """Load a specific CT slice from DICOM file"""
    try:
        ds = pydicom.dcmread(dicom_path)
        pixel_array = ds.pixel_array
        
        # Apply window/level if available
        if hasattr(ds, 'WindowCenter') and hasattr(ds, 'WindowWidth'):
            window_center = ds.WindowCenter
            window_width = ds.WindowWidth
            
            # Handle multiple window values
            if isinstance(window_center, pydicom.multival.MultiValue):
                window_center = window_center[0]
            if isinstance(window_width, pydicom.multival.MultiValue):
                window_width = window_width[0]
            
            img_min = window_center - window_width // 2
            img_max = window_center + window_width // 2
            pixel_array = np.clip(pixel_array, img_min, img_max)
        
        return pixel_array, ds
    except Exception as e:
        print(f"Error loading CT slice: {e}")
        return None, None


def load_rtstruct_contours(rtstruct_path):
    """Load RT Structure contours from DICOM file"""
    try:
        ds = pydicom.dcmread(rtstruct_path)
        
        if not hasattr(ds, 'ROIContourSequence'):
            return {}
        
        contours = {}
        
        # Get ROI names
        roi_names = {}
        if hasattr(ds, 'StructureSetROISequence'):
            for roi in ds.StructureSetROISequence:
                roi_names[roi.ROINumber] = roi.ROIName
        
        # Get contours for each ROI
        for roi_contour in ds.ROIContourSequence:
            roi_number = roi_contour.ReferencedROINumber
            roi_name = roi_names.get(roi_number, f"ROI {roi_number}")
            
            if hasattr(roi_contour, 'ContourSequence'):
                roi_contour_list = []
                for contour in roi_contour.ContourSequence:
                    if hasattr(contour, 'ContourData'):
                        # ContourData is a flat list: [x1, y1, z1, x2, y2, z2, ...]
                        coords = np.array(contour.ContourData).reshape(-1, 3)
                        roi_contour_list.append(coords)
                
                # Get color
                color = [1.0, 0.0, 0.0]  # Default red
                if hasattr(roi_contour, 'ROIDisplayColor'):
                    color = [c / 255.0 for c in roi_contour.ROIDisplayColor]
                
                contours[roi_name] = {
                    'contours': roi_contour_list,
                    'color': color
                }
        
        return contours
    except Exception as e:
        print(f"Error loading RT struct: {e}")
        return {}


def render_ct_with_overlay(ct_path, rtstruct_path, rois_to_include=None):
    """
    Render CT slice with RT structure overlay
    Returns base64 encoded PNG image
    
    Args:
        ct_path: Path to DICOM CT file
        rtstruct_path: Path to DICOM RTSTRUCT file
        rois_to_include: List of ROI numbers/IDs to include (None for all)
    """
    # Load CT slice
    ct_image, ct_ds = load_ct_slice(ct_path)
    if ct_image is None or ct_ds is None:
        return None
    
    # Get CT Z-coordinate
    try:
        z_coord = float(ct_ds.ImagePositionPatient[2])
    except:
        # Fallback if no position (shouldn't happen for valid CT)
        z_coord = 0.0
        
    # Load RT structures
    contours = load_rtstruct_contours(rtstruct_path)
    
    # Create figure
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.imshow(ct_image, cmap='gray')
    ax.axis('off')
    
    # Image Plane information for conversion (assuming axial)
    # Origin (0,0) of the image is Top-Left.
    # ImagePositionPatient is the center of the Top-Left pixel.
    # PixelSpacing is [row_spacing, col_spacing] (mm/pixel)
    
    try:
        origin = np.array([float(x) for x in ct_ds.ImagePositionPatient])
        spacing = np.array([float(x) for x in ct_ds.PixelSpacing])
        # origin[0] is X (increasing to left/right), origin[1] is Y (increasing to bottom)
        
        # Overlay contours
        for roi_name, roi_data in contours.items():
            # Filter by ROI ID/Name if requested
            if rois_to_include is not None and roi_name not in rois_to_include:
                continue
            
            color = roi_data['color']
            for contour_points in roi_data['contours']:
                # Contour points are [x, y, z]
                # Check if this contour is on the current slice (within tolerance)
                # Tolerance is usually half slice thickness or small epsilon
                z_contour = contour_points[0, 2]
                
                if abs(z_contour - z_coord) < 1.0: # 1mm tolerance, adjust as needed
                    # Convert world coordinates to pixel coordinates
                    # pixel_x = (world_x - origin_x) / spacing_x
                    # pixel_y = (world_y - origin_y) / spacing_y
                    
                    pixel_coords = []
                    for point in contour_points:
                        px = (point[0] - origin[0]) / spacing[0]
                        py = (point[1] - origin[1]) / spacing[1]
                        pixel_coords.append([px, py])
                    
                    pixel_coords = np.array(pixel_coords)
                    
                    polygon = Polygon(pixel_coords, fill=False, edgecolor=color, linewidth=2, label=roi_name)
                    ax.add_patch(polygon)
                    
    except Exception as e:
        print(f"Error converting coordinates: {e}")
    
    # Add legend (deduplicate)
    handles, labels = ax.get_legend_handles_labels()
    unique_labels = {}
    for h, l in zip(handles, labels):
        if l not in unique_labels:
            unique_labels[l] = h
            
    if unique_labels:
        ax.legend(unique_labels.values(), unique_labels.keys(), loc='upper right')
    
    plt.title(f'CT + RT Structure Overlay')
    plt.tight_layout()
    
    # Save to buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight', pad_inches=0)
    buf.seek(0)
    plt.close(fig)
    
    # Encode to base64
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    return img_base64

