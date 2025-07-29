"""Image preview utilities."""

import os
import sys
import tempfile
import requests
from PIL import Image, ImageDraw, ImageFont
import subprocess
import atexit
import psutil
import time

if sys.platform == "win32":
    import win32gui
    import win32con

# Global storage for temporary files to prevent premature deletion
_temp_dir = None
_temp_files = []
_viewer_process = None

def _cleanup_temp_files():
    """Clean up temporary files on program exit."""
    global _temp_dir, _temp_files, _viewer_process
    # Kill viewer process if it exists
    if _viewer_process:
        try:
            process = psutil.Process(_viewer_process)
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    for file in _temp_files:
        try:
            if os.path.exists(file):
                os.remove(file)
        except:
            pass
    if _temp_dir and os.path.exists(_temp_dir):
        try:
            os.rmdir(_temp_dir)
        except:
            pass

# Register cleanup function
atexit.register(_cleanup_temp_files)

def get_temp_dir():
    """Get or create temporary directory."""
    global _temp_dir
    if _temp_dir is None or not os.path.exists(_temp_dir):
        _temp_dir = tempfile.mkdtemp(prefix="fieldwire_preview_")
    return _temp_dir

def download_image(url, output_path):
    """Download image from URL to local file.
    
    Args:
        url (str): URL of the image file
        output_path (str): Path to save the image file
        
    Returns:
        bool: True if download successful, False otherwise
    """
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"Error downloading image: {str(e)}")
        return False

def generate_location_preview(image_path, bounds, output_path):
    """Generate preview image with enhanced visual elements.
    
    Args:
        image_path (str): Path to the source image file
        bounds (dict): Bounding box coordinates {x1, y1, x2, y2}
        output_path (str): Path to save the preview image
        
    Returns:
        bool: True if preview generated successfully, False otherwise
    """
    try:
        # Open source image
        with Image.open(image_path) as img:
            # Calculate match dimensions for dynamic padding
            match_width = bounds['x2'] - bounds['x1']
            match_height = bounds['y2'] - bounds['y1']
            padding = max(200, min(match_width, match_height) * 2)  # Dynamic padding based on match size
            
            # Calculate center and crop box
            center_x = (bounds['x1'] + bounds['x2']) / 2
            center_y = (bounds['y1'] + bounds['y2']) / 2
            
            crop_box = (
                max(0, center_x - padding),
                max(0, center_y - padding),
                min(img.width, center_x + padding),
                min(img.height, center_y + padding)
            )
            
            # Crop the image
            preview = img.crop(crop_box)
            
            # Create RGBA version for overlays
            preview = preview.convert('RGBA')
            
            # Create drawing context
            draw = ImageDraw.Draw(preview)
            
            # Add enhanced crosshair at center
            center_local_x = center_x - crop_box[0]
            center_local_y = center_y - crop_box[1]
            
            # Larger crosshair lines with white outline for better visibility
            size = 40  # Increased from 20
            line_width = 3  # Increased from 2
            circle_radius = 25  # Size of the target circle
            
            # Draw white outline for crosshair segments (outside the circle only)
            for offset in [-1, 1]:
                # Left horizontal segment
                draw.line(
                    [(center_local_x - size, center_local_y + offset), 
                     (center_local_x - circle_radius - 5, center_local_y + offset)], 
                    fill='white', 
                    width=line_width + 2
                )
                # Right horizontal segment
                draw.line(
                    [(center_local_x + circle_radius + 5, center_local_y + offset), 
                     (center_local_x + size, center_local_y + offset)], 
                    fill='white', 
                    width=line_width + 2
                )
                # Top vertical segment
                draw.line(
                    [(center_local_x + offset, center_local_y - size), 
                     (center_local_x + offset, center_local_y - circle_radius - 5)], 
                    fill='white', 
                    width=line_width + 2
                )
                # Bottom vertical segment
                draw.line(
                    [(center_local_x + offset, center_local_y + circle_radius + 5), 
                     (center_local_x + offset, center_local_y + size)], 
                    fill='white', 
                    width=line_width + 2
                )
            
            # Draw red crosshair segments (outside the circle only)
            # Left horizontal segment
            draw.line(
                [(center_local_x - size, center_local_y), 
                 (center_local_x - circle_radius - 5, center_local_y)], 
                fill='red', 
                width=line_width
            )
            # Right horizontal segment
            draw.line(
                [(center_local_x + circle_radius + 5, center_local_y), 
                 (center_local_x + size, center_local_y)], 
                fill='red', 
                width=line_width
            )
            # Top vertical segment
            draw.line(
                [(center_local_x, center_local_y - size), 
                 (center_local_x, center_local_y - circle_radius - 5)], 
                fill='red', 
                width=line_width
            )
            # Bottom vertical segment
            draw.line(
                [(center_local_x, center_local_y + circle_radius + 5), 
                 (center_local_x, center_local_y + size)], 
                fill='red', 
                width=line_width
            )
            
            # Draw white outline for outer circle
            draw.ellipse(
                [center_local_x - circle_radius - 1, center_local_y - circle_radius - 1, 
                 center_local_x + circle_radius + 1, center_local_y + circle_radius + 1], 
                outline='white', 
                width=3
            )
            
            # Draw red outer circle
            draw.ellipse(
                [center_local_x - circle_radius, center_local_y - circle_radius, 
                 center_local_x + circle_radius, center_local_y + circle_radius], 
                outline='red', 
                width=2
            )
            
            # Add smaller inner circle (dot)
            inner_radius = 2  # Reduced from 5 to 2
            draw.ellipse(
                [center_local_x - inner_radius, center_local_y - inner_radius, 
                 center_local_x + inner_radius, center_local_y + inner_radius], 
                fill='red'
            )
            
            # Add coordinate information
            try:
                font = ImageFont.truetype("arial.ttf", 14)
            except:
                font = ImageFont.load_default()
                
            info_text = f"Location: X={center_x:.1f}, Y={center_y:.1f}"
            text_bbox = draw.textbbox((10, 10), info_text, font=font)
            
            # Add text background
            draw.rectangle(
                [text_bbox[0]-5, text_bbox[1]-5, text_bbox[2]+5, text_bbox[3]+5],
                fill=(0, 0, 0, 180)
            )
            
            # Draw text
            draw.text((10, 10), info_text, font=font, fill='white')
            
            # Add scale indicator
            scale_length = 100  # pixels
            scale_y = preview.height - 30
            draw.line(
                [(20, scale_y), (20 + scale_length, scale_y)],
                fill='white',
                width=3
            )
            draw.line(
                [(20, scale_y), (20 + scale_length, scale_y)],
                fill='black',
                width=1
            )
            draw.text(
                (20, scale_y - 20),
                f"{scale_length}px",
                font=font,
                fill='white'
            )
            
            # Save the enhanced preview
            preview.save(output_path, "PNG")  # Changed to PNG for better quality
            return True
            
    except Exception as e:
        print(f"Error generating preview: {str(e)}")
        return False

def _window_enum_callback(hwnd, windows):
    """Callback for win32gui.EnumWindows to find preview windows."""
    text = win32gui.GetWindowText(hwnd)
    if text.endswith('preview.jpg'):
        windows.append(hwnd)

def close_preview_windows():
    """Close all open image viewer windows."""
    if sys.platform == "win32":
        # Find all windows with title ending in 'preview.jpg'
        windows = []
        win32gui.EnumWindows(_window_enum_callback, windows)
        for hwnd in windows:
            try:
                # Send close message to window
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            except:
                pass
    elif sys.platform == "darwin":  # macOS
        subprocess.run(['pkill', '-f', 'preview.jpg'], stderr=subprocess.DEVNULL)
    else:  # linux variants
        subprocess.run(['pkill', '-f', 'preview.jpg'], stderr=subprocess.DEVNULL)

def show_preview(preview_path):
    """Open preview image with system default viewer.
    
    Args:
        preview_path (str): Path to the preview image
    """
    try:
        # Close any existing preview first
        close_preview_windows()
        time.sleep(0.1)  # Small delay to ensure previous window is closed
        
        if sys.platform == "win32":
            os.startfile(preview_path)
        elif sys.platform == "darwin":  # macOS
            subprocess.run(['open', preview_path], check=True)
        else:  # linux variants
            subprocess.run(['xdg-open', preview_path], check=True)
        return True
    except Exception as e:
        print(f"Error showing preview: {str(e)}")
        return False

def create_and_show_preview(image_url, bounds, verify_only=False):
    """Download image, generate and show preview for a location.
    
    Args:
        image_url (str): URL of the image file or local file path
        bounds (dict): Bounding box coordinates
        verify_only (bool): Not used, kept for compatibility
        
    Returns:
        bool: True if preview shown successfully, False otherwise
    """
    try:
        # Use persistent temporary directory
        temp_dir = get_temp_dir()
        preview_path = os.path.join(temp_dir, "preview.jpg")
        
        # Track files for cleanup
        _temp_files.append(preview_path)
        
        # Handle local file paths (starting with file://)
        if image_url.startswith('file://'):
            image_path = image_url[7:]  # Remove file:// prefix
        else:
            # For remote URLs, download the image
            image_path = os.path.join(temp_dir, "sheet.jpg")
            _temp_files.append(image_path)
            if not download_image(image_url, image_path):
                return False
            
        # Generate preview
        if not generate_location_preview(image_path, bounds, preview_path):
            return False
            
        # Show preview
        return show_preview(preview_path)
            
    except Exception as e:
        print(f"Error in create_and_show_preview: {str(e)}")
        return False

def download_sheets(sheets, save_dir=None):
    """Download multiple sheets and cache them locally.
    
    Args:
        sheets (list): List of sheet dictionaries containing 'id' and 'file_url'
        save_dir (str, optional): Directory to save permanent copies of sheets
        
    Returns:
        dict: Mapping of sheet IDs to local file paths
    """
    temp_dir = get_temp_dir()
    sheet_paths = {}
    
    print("\nDownloading sheets...")
    for sheet in sheets:
        if not sheet.get('file_url'):
            print(f"Warning: No file URL for sheet {sheet.get('id', 'unknown')}")
            continue
            
        sheet_path = os.path.join(temp_dir, f"sheet_{sheet['id']}.jpg")
        _temp_files.append(sheet_path)  # Track for cleanup
        
        if download_image(sheet['file_url'], sheet_path):
            sheet_paths[sheet['id']] = sheet_path
            print(f"Downloaded sheet: {sheet.get('name', sheet['id'])}")
            
            # If save_dir is provided, save a permanent copy of the sheet
            if save_dir and os.path.exists(save_dir):
                try:
                    sheet_name = sheet.get('name', f"sheet_{sheet['id']}")
                    # Remove invalid characters from filename
                    valid_name = ''.join(c if c.isalnum() or c in ('-', '_', '.') else '_' for c in sheet_name)
                    # Ensure unique filename by adding sheet ID
                    save_path = os.path.join(save_dir, f"{valid_name}_{sheet['id']}.jpg")
                    # Copy the file
                    import shutil
                    shutil.copy2(sheet_path, save_path)
                    print(f"Saved permanent copy to: {save_path}")
                except Exception as e:
                    print(f"Error saving permanent copy: {str(e)}")
        else:
            print(f"Failed to download sheet: {sheet.get('name', sheet['id'])}")
    
    return sheet_paths

def generate_multi_location_preview(image_path, locations, output_path):
    """Generate preview image with multiple task locations.
    
    Args:
        image_path (str): Path to the source image file
        locations (list): List of location dictionaries, each containing:
            - pos_x: X coordinate
            - pos_y: Y coordinate
            - task_type: Task type (COM, DEF, FC, UCI, UCA)
            - is_main: Boolean indicating if this is the main task
        output_path (str): Path to save the preview image
        
    Returns:
        bool: True if preview generated successfully, False otherwise
    """
    try:
        # Color scheme for different task types
        colors = {
            'COM': ('red', 'white'),      # Primary color, outline color
            'DEF': ('blue', 'white'),
            'FC': ('green', 'white'),
            'UCI': ('purple', 'white'),
            'UCA': ('orange', 'white')
        }
        
        # Open source image
        with Image.open(image_path) as img:
            # Find the bounds that encompass all locations with padding
            padding = 200  # Base padding
            min_x = min(loc['pos_x'] for loc in locations)
            max_x = max(loc['pos_x'] for loc in locations)
            min_y = min(loc['pos_y'] for loc in locations)
            max_y = max(loc['pos_y'] for loc in locations)
            
            # Add padding and ensure within image bounds
            crop_box = (
                max(0, min_x - padding),
                max(0, min_y - padding),
                min(img.width, max_x + padding),
                min(img.height, max_y + padding)
            )
            
            # Crop the image
            preview = img.crop(crop_box)
            preview = preview.convert('RGBA')
            draw = ImageDraw.Draw(preview)
            
            try:
                font = ImageFont.truetype("arial.ttf", 14)
            except:
                font = ImageFont.load_default()
            
            # Draw connecting lines between COM and related tasks
            com_location = next((loc for loc in locations if loc['task_type'] == 'COM'), None)
            if com_location:
                com_x = com_location['pos_x'] - crop_box[0]
                com_y = com_location['pos_y'] - crop_box[1]
                
                # Draw lines to related tasks
                for loc in locations:
                    if loc['task_type'] != 'COM':
                        target_x = loc['pos_x'] - crop_box[0]
                        target_y = loc['pos_y'] - crop_box[1]
                        
                        # Draw white outline
                        for offset in [-1, 0, 1]:
                            draw.line(
                                [(com_x + offset, com_y), (target_x + offset, target_y)],
                                fill='white',
                                width=2
                            )
                        # Draw colored line
                        draw.line(
                            [(com_x, com_y), (target_x, target_y)],
                            fill=colors[loc['task_type']][0],
                            width=1
                        )
            
            # Draw markers for each location
            for loc in locations:
                x = loc['pos_x'] - crop_box[0]
                y = loc['pos_y'] - crop_box[1]
                task_type = loc['task_type']
                color = colors[task_type][0]
                outline_color = colors[task_type][1]
                
                # Marker size based on whether it's the main task
                circle_radius = 25 if loc['is_main'] else 15
                
                if loc['is_main']:
                    # Draw crosshair for main task (COM)
                    size = 40
                    line_width = 3
                    
                    # Draw white outline for crosshair
                    for offset in [-1, 1]:
                        # Horizontal
                        draw.line(
                            [(x - size, y + offset), (x - circle_radius - 5, y + offset)],
                            fill=outline_color,
                            width=line_width + 2
                        )
                        draw.line(
                            [(x + circle_radius + 5, y + offset), (x + size, y + offset)],
                            fill=outline_color,
                            width=line_width + 2
                        )
                        # Vertical
                        draw.line(
                            [(x + offset, y - size), (x + offset, y - circle_radius - 5)],
                            fill=outline_color,
                            width=line_width + 2
                        )
                        draw.line(
                            [(x + offset, y + circle_radius + 5), (x + offset, y + size)],
                            fill=outline_color,
                            width=line_width + 2
                        )
                    
                    # Draw colored crosshair
                    draw.line([(x - size, y), (x - circle_radius - 5, y)], fill=color, width=line_width)
                    draw.line([(x + circle_radius + 5, y), (x + size, y)], fill=color, width=line_width)
                    draw.line([(x, y - size), (x, y - circle_radius - 5)], fill=color, width=line_width)
                    draw.line([(x, y + circle_radius + 5), (x, y + size)], fill=color, width=line_width)
                
                # Draw circle for all tasks
                # White outline
                draw.ellipse(
                    [x - circle_radius - 1, y - circle_radius - 1,
                     x + circle_radius + 1, y + circle_radius + 1],
                    outline=outline_color,
                    width=3
                )
                # Colored circle
                draw.ellipse(
                    [x - circle_radius, y - circle_radius,
                     x + circle_radius, y + circle_radius],
                    outline=color,
                    width=2
                )
            
            # Add scale indicator
            scale_length = 100  # pixels
            scale_y = preview.height - 30
            draw.line(
                [(20, scale_y), (20 + scale_length, scale_y)],
                fill='white',
                width=3
            )
            draw.line(
                [(20, scale_y), (20 + scale_length, scale_y)],
                fill='black',
                width=1
            )
            draw.text(
                (20, scale_y - 20),
                f"{scale_length}px",
                font=font,
                fill='white'
            )
            
            # Save the preview
            preview.save(output_path, "PNG")
            return True
            
    except Exception as e:
        print(f"Error generating preview: {str(e)}")
        return False

def create_and_show_multi_preview(image_url, locations):
    """Create and show preview with multiple task locations.
    
    Args:
        image_url (str): URL of the image file or local file path
        locations (list): List of location dictionaries with task positions
        
    Returns:
        bool: True if preview shown successfully, False otherwise
    """
    try:
        # Use persistent temporary directory
        temp_dir = get_temp_dir()
        preview_path = os.path.join(temp_dir, "preview.jpg")
        
        # Track files for cleanup
        _temp_files.append(preview_path)
        
        # Handle local file paths (starting with file://)
        if image_url.startswith('file://'):
            image_path = image_url[7:]  # Remove file:// prefix
        else:
            # For remote URLs, download the image
            image_path = os.path.join(temp_dir, "sheet.jpg")
            _temp_files.append(image_path)
            if not download_image(image_url, image_path):
                return False
            
        # Generate preview
        if not generate_multi_location_preview(image_path, locations, preview_path):
            return False
            
        # Show preview
        return show_preview(preview_path)
            
    except Exception as e:
        print(f"Error in create_and_show_multi_preview: {str(e)}")
        return False 