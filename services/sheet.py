"""Sheet service for Fieldwire API."""

from core.auth import AuthManager
from utils.decorators import paginate_response, update_last_response
from utils.input_helpers import (
    get_user_input, 
    prompt_user_for_xml_file, 
    get_location_confirmation,
    get_preview_error_choice,
    get_location_confirmation_with_adjustment,
    get_single_keypress  # Add this import for global keyboard shortcuts
)
from utils.pdf_helpers import create_and_show_preview, close_preview_windows, download_sheets, create_and_show_multi_preview
import time
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, Future
from typing import List, Dict, Tuple, Any, Optional, Union
import tkinter as tk
from tkinter import ttk, filedialog
from PIL import Image, ImageTk
import io
import requests
import threading
import queue
import os
import sys

# Constants for distance adjustment
MAX_DISTANCE = 300  # Maximum reasonable distance
DISTANCE_STEP = 10  # Amount to adjust distance by

# Global lock to prevent threading conflicts between preview windows
_preview_window_lock = threading.Lock()
_active_preview_window = None

# Global state to persist marker visibility between preview windows
_markers_visible_state = True

# Global keyboard management to prevent multiple listeners
_global_keyboard_thread = None
_global_keyboard_stop = threading.Event()

# Utility function for processing tkinter events
def process_events():
    """Process pending tkinter events to keep UI responsive."""
    try:
        # Process all pending events
        while tk._default_root and tk._default_root.dooneevent(0):
            pass
        
        # Process events for any active preview window
        global _active_preview_window
        if _active_preview_window is not None:
            try:
                if hasattr(_active_preview_window, 'root') and _active_preview_window.root.winfo_exists():
                    _active_preview_window.root.update()
            except Exception:
                pass  # Ignore errors
    except Exception:
        pass  # Ignore any errors to prevent crashing the main process

class PreviewWindow:
    """Custom preview window for task location adjustment with global keyboard shortcuts."""
    
    def __init__(self, image_url: str, locations: List[Dict[str, Any]], current_distance: int, task_name: str = None, enable_distance_controls: bool = True):
        # Use global lock to prevent conflicts between window instances
        global _active_preview_window
        
        with _preview_window_lock:
            # Ensure any previous window is properly closed
            if _active_preview_window is not None:
                try:
                    _active_preview_window._force_cleanup()
                except Exception:
                    pass  # Ignore cleanup errors
            
            # Set this as the active window
            _active_preview_window = self
        
        self.root = tk.Tk()
        
        # Set window title with task name if provided
        if task_name:
            self.root.title(f"Task Location Preview - {task_name}")
        else:
            self.root.title("Task Location Preview")
        
        # Store parameters
        self.locations = locations
        self.current_distance = current_distance
        self.user_choice = None
        self.scale_factor = 1.0  # Store the scale factor for coordinate conversion
        self.image_url = image_url  # Store image URL for later loading
        self.task_name = task_name  # Store task name for display
        self.enable_distance_controls = enable_distance_controls  # For BC mode compatibility
        global _markers_visible_state
        self.markers_visible = _markers_visible_state  # Use persistent global state
        self.marker_objects = []  # Store marker canvas objects for toggling
        
        # Debug output for distance controls setting
        print(f"Preview window initialized with enable_distance_controls={enable_distance_controls}")
        print(f"Markers will be {'visible' if self.markers_visible else 'hidden'} (persistent from previous window)")
        
        # Simplified keyboard shortcut support - no threading locks needed
        
        # Create main frame with padding
        self.main_frame = ttk.Frame(self.root, padding="10")
        self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        
        # Create image container frame
        self.image_frame = ttk.Frame(self.main_frame)
        self.image_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Create button container frame
        self.button_frame = ttk.Frame(self.main_frame)
        self.button_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(20, 0))
        
        # Configure grid weights for main frame
        self.main_frame.grid_rowconfigure(0, weight=1)  # Image area expands
        self.main_frame.grid_rowconfigure(2, weight=0)  # Button area fixed
        self.main_frame.grid_columnconfigure(0, weight=1)
        
        # Create status label with task name if provided
        if self.task_name:
            status_text = f"Task: {self.task_name} | Current spacing: {current_distance} pixels"
        else:
            status_text = f"Current spacing: {current_distance} pixels"
        
        self.status_label = ttk.Label(
            self.main_frame,
            text=status_text
        )
        self.status_label.grid(row=1, column=0, columnspan=2, pady=10)
        
        # Create control buttons
        self._create_control_buttons()
        
        # Maximize window and ensure it gets proper focus
        self.root.state('zoomed')
        
        # Make window stay on top and modal - using stronger focus methods
        self.root.attributes('-topmost', True)  # Always on top
        self.root.grab_set()  # Modal window
        
        # Setup keyboard shortcuts
        self._setup_keyboard_shortcuts()
        
        # Load image after window is fully created
        self.root.after(100, self._load_and_display_image)
        
        # Force focus after window is fully loaded - use multiple methods
        self.root.after(300, self._force_initial_focus)
        
        # Handle window close event
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)
        
        # Update window to ensure it's ready to display
        self.root.update_idletasks()
        
    def _setup_keyboard_shortcuts(self):
        """Setup keyboard shortcuts that directly simulate button clicks."""
        
        print("\nKeyboard shortcuts active:")
        print("  y = Accept location")
        print("  n = Next match (cycles within same opening number)") 
        print("  s = Skip task (moves to next opening number)")
        print("  t = Toggle markers visibility")
        if self.enable_distance_controls:
            print("  z = Increase spacing")
            print("  x = Decrease spacing")
        print("  Arrow keys = Move position")
        print("  (Click on preview window first, then use keyboard)")
        
        # Simple approach: keyboard shortcuts directly call the same methods as buttons
        # This eliminates all threading complexity
        
        self.root.bind('<Key-y>', self._on_key_y)
        self.root.bind('<Key-Y>', self._on_key_y)
        self.root.bind('<Key-n>', self._on_key_n)
        self.root.bind('<Key-N>', self._on_key_n)
        self.root.bind('<Key-s>', self._on_key_s)
        self.root.bind('<Key-S>', self._on_key_s)
        self.root.bind('<Key-t>', self._on_key_t)
        self.root.bind('<Key-T>', self._on_key_t)
        
        # Arrow keys
        self.root.bind('<Key-Up>', self._on_key_up)
        self.root.bind('<Key-Down>', self._on_key_down)
        self.root.bind('<Key-Left>', self._on_key_left)
        self.root.bind('<Key-Right>', self._on_key_right)
        
        # Distance controls (only if enabled)
        if self.enable_distance_controls:
            print("Binding Z and X keys for distance control")
            self.root.bind('<Key-z>', self._on_key_z)
            self.root.bind('<Key-Z>', self._on_key_z)
            self.root.bind('<Key-x>', self._on_key_x)
            self.root.bind('<Key-X>', self._on_key_x)
        else:
            print("Distance controls disabled - not binding Z and X keys")
        
        # Make window focusable
        self.root.focus_set()
    
    def _on_key_y(self, event=None):
        print("Y key pressed")
        self._safe_handle_choice('y')
    
    def _on_key_n(self, event=None):
        print("N key pressed")
        self._safe_handle_choice('n')
    
    def _on_key_s(self, event=None):
        print("S key pressed")
        self._safe_handle_choice('s')
    
    def _on_key_t(self, event=None):
        print("T key pressed - toggling markers")
        self._toggle_markers()
    
    def _on_key_up(self, event=None):
        print("UP key pressed")
        self._safe_handle_choice('up')
    
    def _on_key_down(self, event=None):
        print("DOWN key pressed")
        self._safe_handle_choice('down')
    
    def _on_key_left(self, event=None):
        print("LEFT key pressed")
        self._safe_handle_choice('left')
    
    def _on_key_right(self, event=None):
        print("RIGHT key pressed")
        self._safe_handle_choice('right')
    
    def _on_key_z(self, event=None):
        print("Z key pressed")
        if self.enable_distance_controls:
            print("Distance controls enabled - processing Z key")
            self._safe_handle_choice('z')
        else:
            print("Distance controls disabled - ignoring Z key")
    
    def _on_key_x(self, event=None):
        print("X key pressed")
        if self.enable_distance_controls:
            print("Distance controls enabled - processing X key")
            self._safe_handle_choice('x')
        else:
            print("Distance controls disabled - ignoring X key")
    
    def _safe_handle_choice(self, choice: str):
        """Thread-safe choice handler that prevents hangs."""
        # Use a simple flag-based approach instead of locks
        if hasattr(self, 'choice_processed') and self.choice_processed:
            return  # Already processed, ignore
        
        # Mark as processed immediately
        self.choice_processed = True
        
        # Schedule the actual choice handling in the main thread
        self.root.after_idle(lambda: self._handle_choice(choice))
    
    def _ensure_focus(self):
        """This method has been replaced by _force_initial_focus to avoid threading issues."""
        pass
    
    def _handle_keyboard_choice(self, key: str):
        """This method has been replaced by individual key handlers to avoid threading issues."""
        pass
    
    def _on_window_close(self):
        """Handle window close event."""
        global _active_preview_window
        
        # Set a default choice if the user closes the window without choosing
        if not hasattr(self, 'user_choice') or self.user_choice is None:
            print("Window closed by user without making a choice - defaulting to 'skip'")
            self.user_choice = 's'  # Default to skip if window is closed
        
        # Clear global reference
        with _preview_window_lock:
            if _active_preview_window == self:
                _active_preview_window = None
        
        # Safely destroy the window
        try:
            if self.root.winfo_exists():
                self.root.quit()  # Stop the event loop first
                self.root.destroy()
        except tk.TclError:
            pass  # Window already destroyed

    def _on_mouse_wheel(self, event):
        """Handle mouse wheel scrolling."""
        if event.delta > 0:
            # Scroll up (move image down)
            self.canvas.yview_scroll(-1, "units")
        else:
            # Scroll down (move image up)
            self.canvas.yview_scroll(1, "units")
            
    def _load_and_display_image(self):
        """Load and display the sheet image with task locations."""
        try:
            # Load image
            if self.image_url.startswith('file://'):
                image_path = self.image_url[7:]
                image = Image.open(image_path)
            else:
                response = requests.get(self.image_url)
                image = Image.open(io.BytesIO(response.content))
            
            # Store original image dimensions
            self.original_width = image.width
            self.original_height = image.height
            
            # Get window dimensions
            self.root.update_idletasks()  # Ensure window is fully updated
            window_width = self.root.winfo_width()
            window_height = self.root.winfo_height()
            
            # Calculate the area around the tasks
            min_x = min(loc['pos_x'] for loc in self.locations)
            max_x = max(loc['pos_x'] for loc in self.locations)
            min_y = min(loc['pos_y'] for loc in self.locations)
            max_y = max(loc['pos_y'] for loc in self.locations)
            
            # Add padding around the task area
            padding = 200
            task_area_width = max_x - min_x + padding * 2
            task_area_height = max_y - min_y + padding * 2
            
            # Calculate zoom factor to make task area fill most of the window
            image_area_width = window_width - 40  # 20px padding on each side
            image_area_height = window_height - 150  # Account for buttons, status, and padding
            
            zoom_factor = min(
                image_area_width / task_area_width,
                image_area_height / task_area_height
            )
            
            # Calculate new dimensions
            new_width = int(image.width * zoom_factor)
            new_height = int(image.height * zoom_factor)
            
            # Resize image
            image = image.resize((new_width, new_height), Image.LANCZOS)
            self.scale_factor = zoom_factor  # Store the scale factor
            
            # Create canvas with fixed size
            self.canvas = tk.Canvas(
                self.image_frame,
                width=image_area_width,
                height=image_area_height,
                scrollregion=(0, 0, new_width, new_height)
            )
            self.canvas.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
            
            # Add scrollbars
            h_scroll = ttk.Scrollbar(self.image_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
            v_scroll = ttk.Scrollbar(self.image_frame, orient=tk.VERTICAL, command=self.canvas.yview)
            self.canvas.configure(xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)
            
            h_scroll.grid(row=1, column=0, sticky=(tk.W, tk.E))
            v_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))
            
            # Display image
            self.photo = ImageTk.PhotoImage(image)
            self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
            
            # Bind mouse wheel event
            self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)  # Windows
            
            # Find UCI task for centering
            uci_task = next((loc for loc in self.locations if loc['is_main']), None)
            if uci_task:
                # Center the view on the UCI task
                center_x = uci_task['pos_x'] * zoom_factor
                center_y = uci_task['pos_y'] * zoom_factor
                
                # Calculate scroll position to center the UCI task
                x_scroll = (center_x - image_area_width / 2) / new_width
                y_scroll = (center_y - image_area_height / 2) / new_height
                
                # Ensure scroll position is within bounds
                x_scroll = max(0, min(x_scroll, 1))
                y_scroll = max(0, min(y_scroll, 1))
                
                self.canvas.xview_moveto(x_scroll)
                self.canvas.yview_moveto(y_scroll)
            
            # Draw task locations with scaled coordinates
            self.marker_objects = []  # Clear previous markers
            for location in self.locations:
                # Scale coordinates based on the image resize ratio
                x = location['pos_x'] * self.scale_factor
                y = location['pos_y'] * self.scale_factor
                
                # Draw the task location marker
                color = 'red' if location['is_main'] else 'blue'
                marker_size = 5 * self.scale_factor  # Scale the marker size
                
                # Draw the marker as hollow circle and store reference
                # Set initial state based on persistent visibility setting
                initial_state = 'normal' if self.markers_visible else 'hidden'
                marker = self.canvas.create_oval(
                    x-marker_size, y-marker_size, x+marker_size, y+marker_size,
                    fill='',
                    outline=color,
                    width=2,
                    state=initial_state
                )
                self.marker_objects.append(marker)
                
        except Exception as e:
            print(f"Error loading image: {str(e)}")
            self.root.destroy()
            raise
            
    def _create_control_buttons(self):
        """Create control buttons for user interaction."""
        # Create a frame for movement buttons
        movement_frame = ttk.Frame(self.button_frame)
        movement_frame.pack(side=tk.LEFT, padx=20)
        
        # Create movement buttons
        ttk.Button(
            movement_frame,
            text="↑",
            command=lambda: self._handle_choice('up')
        ).grid(row=0, column=1, padx=2, pady=2)
        
        ttk.Button(
            movement_frame,
            text="←",
            command=lambda: self._handle_choice('left')
        ).grid(row=1, column=0, padx=2, pady=2)
        
        ttk.Button(
            movement_frame,
            text="→",
            command=lambda: self._handle_choice('right')
        ).grid(row=1, column=2, padx=2, pady=2)
        
        ttk.Button(
            movement_frame,
            text="↓",
            command=lambda: self._handle_choice('down')
        ).grid(row=2, column=1, padx=2, pady=2)
        
        # Create a separator
        ttk.Separator(self.button_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=20, fill=tk.Y)
        
        # Only show distance controls if enabled (disabled for BC mode)
        if self.enable_distance_controls:
            print("Creating distance control buttons (enabled)")
            # Increase distance button
            self.increase_btn = ttk.Button(
                self.button_frame,
                text="Increase Spacing (z)",
                command=lambda: self._handle_choice('z')
            )
            self.increase_btn.pack(side=tk.LEFT, padx=5)
            
            # Decrease distance button
            self.decrease_btn = ttk.Button(
                self.button_frame,
                text="Decrease Spacing (x)",
                command=lambda: self._handle_choice('x')
            )
            self.decrease_btn.pack(side=tk.LEFT, padx=5)
        else:
            print("Distance control buttons not created (disabled)")
        
        # Accept location button
        self.accept_btn = ttk.Button(
            self.button_frame,
            text="Accept Location (y)",
            command=lambda: self._handle_choice('y'),
            style='Accent.TButton'
        )
        self.accept_btn.pack(side=tk.LEFT, padx=5)
        
        # Skip button
        self.skip_btn = ttk.Button(
            self.button_frame,
            text="Skip Task (s)",
            command=lambda: self._handle_choice('s')
        )
        self.skip_btn.pack(side=tk.LEFT, padx=5)
        
        # Next match button
        self.next_btn = ttk.Button(
            self.button_frame,
            text="Next Match (n)",
            command=lambda: self._handle_choice('n')
        )
        self.next_btn.pack(side=tk.LEFT, padx=5)
        
        # Toggle markers button
        self.toggle_btn = ttk.Button(
            self.button_frame,
            text="Toggle Markers (t)",
            command=self._toggle_markers
        )
        self.toggle_btn.pack(side=tk.LEFT, padx=5)
        
        # Configure style for accept button
        style = ttk.Style()
        style.configure('Accent.TButton', font=('Arial', 10, 'bold'))
        
    def _handle_choice(self, choice: str):
        """Handle user choice and close window - exactly like button clicks."""
        # Store the user's choice
        self.user_choice = choice
        print(f"User choice registered: {choice}")
        
        # Log the state of distance controls for debugging
        print(f"Current state: distance_controls={self.enable_distance_controls}, current_distance={self.current_distance}")
        
        # Handle distance adjustments (only if enabled)
        if choice == 'z' and self.enable_distance_controls:  # Increase distance
            print(f"INCREASING spacing from {self.current_distance} to {min(self.current_distance + DISTANCE_STEP, MAX_DISTANCE)}")
            self.current_distance = min(self.current_distance + DISTANCE_STEP, MAX_DISTANCE)
            # Close window and return new distance so positions can be recalculated
            self.root.quit()  # Stop the event loop first
            self.root.destroy()
            return
        elif choice == 'x' and self.enable_distance_controls:  # Decrease distance
            print(f"DECREASING spacing from {self.current_distance} to {max(self.current_distance - DISTANCE_STEP, 0)}")
            self.current_distance = max(self.current_distance - DISTANCE_STEP, 0)
            # Close window and return new distance so positions can be recalculated
            self.root.quit()  # Stop the event loop first
            self.root.destroy()
            return
        elif choice == 'x' and not self.enable_distance_controls:
            print("X key pressed but distance controls are disabled")
        elif choice == 'z' and not self.enable_distance_controls:
            print("Z key pressed but distance controls are disabled")
            
        # For all other choices, close window
        print(f"Closing preview window with choice: {choice}")
        self.root.quit()  # Stop the event loop first
        self.root.destroy()  # Then destroy the window
    
    def show(self) -> Tuple[str, int]:
        """Show the window and return user choice and current distance."""
        global _active_preview_window
        
        try:
            # Make sure window is visible and on top
            self.root.deiconify()
            self.root.attributes('-topmost', True)
            self.root.focus_force()
            print("Showing preview window - waiting for user interaction...")
            
            # Debug the focus state
            print(f"Window focus state before mainloop: {self.root.focus_get()}")
            
            # Force window to update before entering mainloop
            self.root.update()
            time.sleep(0.2)  # Short delay to ensure window is visible
            
            # Enter mainloop to process events
            if not hasattr(self, 'user_choice') or self.user_choice is None:
                print("Entering main event loop - this will block until user makes a choice")
                print(f"Distance controls are {'enabled' if self.enable_distance_controls else 'disabled'}")
                
                # Manual event loop to allow processing in a custom way
                if os.name == 'nt' and 'JUPYTER_KERNEL' not in os.environ:  # Extra care for Windows non-Jupyter environment
                    # Use native mainloop on Windows
                    self.root.mainloop()
                else:
                    # Custom event loop that allows us to break out when user choice is made
                    while not hasattr(self, 'user_choice') or self.user_choice is None:
                        try:
                            self.root.update()
                            time.sleep(0.05)  # Short sleep to prevent 100% CPU
                        except Exception as e:
                            # If an error occurs (e.g., window closed), break out
                            print(f"Event loop interrupted: {str(e)}")
                            break
            
            print(f"User choice received: {self.user_choice}, final distance: {self.current_distance}")
            
        except Exception as e:
            print(f"Error in preview window: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            # Clear global reference
            with _preview_window_lock:
                if _active_preview_window == self:
                    _active_preview_window = None
                    
        return self.user_choice, self.current_distance
        
    def _force_initial_focus(self):
        """Force initial focus using multiple methods to ensure keyboard shortcuts work."""
        try:
            if self.root.winfo_exists():
                # Use multiple focus methods for better reliability
                self.root.deiconify()  # Ensure window is not minimized
                self.root.lift()       # Bring to front
                self.root.attributes('-topmost', True)  # Ensure it stays on top
                self.root.focus_force()  # Force focus
                self.root.grab_set()   # Ensure modal behavior
                
                # Additional method to force window to front on Windows
                if os.name == 'nt':  # Check if running on Windows
                    try:
                        import ctypes
                        hwnd = ctypes.windll.user32.GetForegroundWindow()
                        ctypes.windll.user32.SetForegroundWindow(self.root.winfo_id())
                    except Exception:
                        pass  # Ignore if this fails
                
                print("Preview window focused - keyboard shortcuts ready!")
                
                # Update the window to process any pending events
                self.root.update()
        except tk.TclError:
            # Window was destroyed, nothing to do
            pass

    def _toggle_markers(self):
        """Toggle visibility of task location markers."""
        if not hasattr(self, 'canvas') or not self.canvas:
            return
            
        global _markers_visible_state
        self.markers_visible = not self.markers_visible
        _markers_visible_state = self.markers_visible  # Save state globally
        
        if self.markers_visible:
            print("Showing markers")
            # Show all markers
            for marker in self.marker_objects:
                self.canvas.itemconfig(marker, state='normal')
        else:
            print("Hiding markers")
            # Hide all markers
            for marker in self.marker_objects:
                self.canvas.itemconfig(marker, state='hidden')

    def _force_cleanup(self):
        """Force cleanup of this window instance."""
        try:
            if self.root and self.root.winfo_exists():
                self.root.quit()
                self.root.destroy()
        except Exception:
            pass

class SheetService(AuthManager):
    """Service for sheet operations."""

    class LocationData:
        """Container for location search results."""
        def __init__(self, sheet, sheet_path, center_x, center_y):
            self.sheet = sheet
            self.sheet_path = sheet_path
            self.center_x = center_x
            self.center_y = center_y

    class FutureSearchData:
        """Container for future search data."""
        def __init__(self, number, locations):
            self.number = number
            self.locations = locations

    @paginate_response()
    def get_all_sheets_in_project(self, project_id, filter_option='active', floorplan_id=None, folder_id=None):
        """Get all sheets in a project with pagination support.
        
        Args:
            project_id (str): Project ID
            filter_option (str): Filter for sheets - 'all', 'active', or 'deleted'
            floorplan_id (str, optional): Filter sheets by floorplan ID
            folder_id (str, optional): Filter sheets by folder ID
            
        Returns:
            tuple: URL and headers for pagination decorator
        """
        url = f"{self.project_base_url}/projects/{project_id}/sheets"
        
        # Validate filter option
        if filter_option not in ['all', 'active', 'deleted']:
            print(f"Invalid filter option '{filter_option}'. Defaulting to 'active'.")
            filter_option = 'active'
        
        # Build headers
        headers = {'Fieldwire-Filter': filter_option}
        
        # Build params for filtering
        params = {}
        if floorplan_id:
            params['filters[floorplan_id_eq]'] = floorplan_id
        if folder_id:
            params['filters[folder_id_eq]'] = folder_id
        
        # Return URL, headers, and params for the decorator to handle
        return url, headers, params

    @paginate_response()
    def get_all_floorplans_in_project(self, project_id, filter_option='active'):
        """Get all floorplans in a project with pagination support.
        
        Args:
            project_id (str): Project ID
            filter_option (str): Filter for floorplans - 'all', 'active', or 'deleted'
            
        Returns:
            tuple: URL and headers for pagination decorator
        """
        url = f"{self.project_base_url}/projects/{project_id}/floorplans"
        
        # Validate filter option
        if filter_option not in ['all', 'active', 'deleted']:
            print(f"Invalid filter option '{filter_option}'. Defaulting to 'active'.")
            filter_option = 'active'
        
        # Return URL and headers for the decorator to handle
        headers = {'Fieldwire-Filter': filter_option}
        return url, headers

    @paginate_response()
    def get_all_folders_in_project(self, project_id, filter_option='active'):
        """Get all folders in a project with pagination support.
        
        Args:
            project_id (str): Project ID
            filter_option (str): Filter for folders - 'all', 'active', or 'deleted'
            
        Returns:
            tuple: URL and headers for pagination decorator
        """
        url = f"{self.project_base_url}/projects/{project_id}/folders"
        
        # Validate filter option
        if filter_option not in ['all', 'active', 'deleted']:
            print(f"Invalid filter option '{filter_option}'. Defaulting to 'active'.")
            filter_option = 'active'
        
        # Return URL and headers for the decorator to handle
        headers = {'Fieldwire-Filter': filter_option}
        return url, headers

    @update_last_response()
    def batch_export_sheets(self, project_id, sheet_ids):
        """Export multiple sheets as PDF.
        
        Args:
            project_id (str): Project ID
            sheet_ids (list): List of sheet IDs to export
            
        Returns:
            str: Job ID for the export task
            
        Note:
            The order of sheets in the exported PDF will match the order
            of sheet_ids in the request.
        """
        url = f"{self.project_base_url}/projects/{project_id}/sheets/batch_export"
        
        payload = {
            "sheet_ids": sheet_ids,
            "file_name": f"project_{project_id}_sheets",
            "options": {
                "markups": True
            }
        }
        
        response = self.send_request(
            "POST", 
            url, 
            json=payload,
            expected_status_codes=[202]
        )
        
        if self.validate_response(response, [202]):
            return response.json().get('jid')
        return None

    def poll_export_status(self, project_id, job_id, timeout=120):
        """Poll for sheet export job completion with progress indicator.
        
        Args:
            project_id (str): Project ID
            job_id (str): Export job ID
            timeout (int): Maximum time to wait in seconds
            
        Returns:
            dict: Export result data including PDF URL and metadata
        """
        url = f"{self.project_base_url}/projects/{project_id}/sheets/batch_export"
        start_time = time.time()
        
        with tqdm(desc="Exporting sheets", unit="check") as pbar:
            while True:
                if time.time() - start_time > timeout:
                    raise TimeoutError("Sheet export timed out")
                
                response = self.send_request(
                    "POST", 
                    url, 
                    json={"jid": job_id},
                    expected_status_codes=[200, 202]
                )
                
                if response.status_code == 200:
                    result = response.json()
                    print("\nExport completed. Response:", result)
                    
                    # The API returns the URL in the 'url' field
                    if 'url' in result:
                        return {'pdf_url': result['url']}
                    else:
                        print("Warning: Response does not contain expected 'url' field")
                        print("Full response content:", result)
                        return None
                
                pbar.update(1)
                time.sleep(5)

    @update_last_response()
    def search_text_on_sheet(self, project_id, sheet_id, search_text):
        """Search for text on a sheet and get bounding box coordinates.
        
        Args:
            project_id (str): Project ID
            sheet_id (str): Sheet ID to search on
            search_text (str): Text to search for
            
        Returns:
            list: List of search results with bounding box coordinates
        """
        url = f"{self.project_base_url}/projects/{project_id}/sheets/{sheet_id}/sheet_highlights"
        
        params = {
            "q": search_text  # The API expects 'q' parameter for the search query
        }
        
        # Log the API search request
        print(f"Sending API request to search for text '{search_text}' on sheet {sheet_id}")
        
        response = self.send_request(
            "GET", 
            url, 
            params=params,
            expected_status_codes=[200]
        )
        
        if not self.validate_response(response, [200]):
            print(f"Search API request failed for text '{search_text}' on sheet {sheet_id}")
            return []
            
        results = response.json()
        result_count = len(results)
        highlight_count = sum(len(r.get('highlights', [])) for r in results)
        
        # Log the search results
        print(f"Search for '{search_text}' found {result_count} text matches with {highlight_count} highlights on sheet {sheet_id}")
            
        if not results:
            return []
            
        # Transform the API response into our expected format
        processed_results = []
        for result in results:
            # Only process results where the text is an exact case-insensitive match
            result_text = result.get('text', '')
            if result_text.lower() == search_text.lower():
                # Each result can have multiple highlights
                for highlight in result.get('highlights', []):
                    processed_result = {
                        'text': result.get('text'),
                        'bounds': {
                            'x1': highlight.get('xmin'),
                            'x2': highlight.get('xmax'),
                            'y1': highlight.get('ymin'),
                            'y2': highlight.get('ymax')
                        }
                    }
                    if all(v is not None for v in processed_result['bounds'].values()):
                        processed_results.append(processed_result)
            else:
                # Log filtered out partial matches for debugging
                print(f"Filtered out partial match: '{result_text}' (searching for '{search_text}')")
                    
        print(f"Processed {len(processed_results)} valid highlights for '{search_text}' on sheet {sheet_id}")
        return processed_results

    @update_last_response()
    def update_task_location(self, project_id, task_id, floorplan_id, pos_x, pos_y, last_editor_user_id):
        """Update a task's location on a sheet.
        
        Args:
            project_id (str): Project ID
            task_id (str): Task ID to update
            floorplan_id (str): Sheet/Floorplan ID where task will be located
            pos_x (float): X coordinate
            pos_y (float): Y coordinate
            last_editor_user_id (int): User ID of the person making the update
            
        Returns:
            dict: Updated task data
        """
        url = f"{self.project_base_url}/projects/{project_id}/tasks/{task_id}"
    
        # Validate coordinates
        if not isinstance(pos_x, (int, float)) or not isinstance(pos_y, (int, float)):
            raise ValueError("Coordinates must be numeric values")
            
        if not isinstance(last_editor_user_id, int):
            raise ValueError("last_editor_user_id must be an integer")
        
        # Payload with required parameters including is_local
        payload = {
            "floorplan_id": floorplan_id,
            "pos_x": pos_x,
            "pos_y": pos_y,
            "last_editor_user_id": last_editor_user_id,
            "is_local": True  # Required when positioning task on floorplan
        }
    
        # Log the API request being made
        print(f"Sending API request to update task {task_id} at position ({pos_x}, {pos_y}) on floorplan {floorplan_id}")
        
        response = self.send_request(
            "PATCH", 
            url, 
            json=payload,
            expected_status_codes=[200, 201]  # Accept both 200 and 201 as success
        )
        
        # Print response details
        print("\nAPI Response Details:")
        print(f"Status Code: {response.status_code}")
        print(f"Response Body: {response.json().get('id', 'Unknown')}")
        
        if self.validate_response(response, [200, 201]):  # Accept both 200 and 201 as success
            return response.json()
        return None

    @update_last_response()
    def get_sheet_by_id(self, project_id, sheet_id):
        """Get details of a specific sheet.
        
        Args:
            project_id (str): Project ID
            sheet_id (str): Sheet ID
            
        Returns:
            dict: Sheet details including file_url
        """
        url = f"{self.project_base_url}/projects/{project_id}/sheets/{sheet_id}"
        
        response = self.send_request(
            "GET",
            url,
            expected_status_codes=[200]
        )
        
        if self.validate_response(response, [200]):
            return response.json()
        return None

    def _search_number_across_sheets_with_rate_limit(self, executor, project_id, sheets, sheet_paths, number, api_limit=10):
        """Search for one opening number across all sheets using multi-threading, respecting API rate limit."""
        locations = []
        search_futures = []
        start_time = time.time()
        calls_this_second = 0
        
        # Log the start of the search process
        print(f"\nStarting search for opening number '{number}' across {len(sheets)} sheets...")
        
        # Debug: List all sheets that will be searched
        print("Sheets to be searched:")
        for i, sheet in enumerate(sheets, 1):
            sheet_name = sheet.get('name', 'Unnamed')
            sheet_id = sheet.get('id', 'Unknown')
            folder_id = sheet.get('folder_id', 'None')
            print(f"  {i}. {sheet_name} (ID: {sheet_id}, Folder: {folder_id})")
        
        for i, sheet in enumerate(sheets):
            # Rate limiting: 10 calls per second
            if calls_this_second >= api_limit:
                elapsed = time.time() - start_time
                if elapsed < 1.0:
                    time.sleep(1.0 - elapsed)
                start_time = time.time()
                calls_this_second = 0
            # Print which opening number is being searched on which sheet
            print(f"Searching for opening number '{number}' on sheet '{sheet['name']}' (ID: {sheet['id']})")
            future = executor.submit(
                self.search_text_on_sheet,
                project_id,
                sheet['id'],
                number
            )
            search_futures.append((sheet, future))
            calls_this_second += 1
        
        # Log the collection of results
        print(f"Collecting search results for opening number '{number}'...")
        match_count = 0
        
        for sheet, future in search_futures:
            try:
                search_results = future.result()
                if not search_results:
                    continue
                sheet_path = sheet_paths.get(sheet['id'])
                if not sheet_path:
                    print(f"Failed to get sheet image for {sheet['name']}. Skipping.")
                    continue
                for result in search_results:
                    bounds = result.get('bounds', {})
                    if not bounds:
                        continue
                    center_x = (bounds.get('x1', 0) + bounds.get('x2', 0)) / 2
                    center_y = (bounds.get('y1', 0) + bounds.get('y2', 0)) / 2
                    locations.append(self.LocationData(
                        sheet=sheet,
                        sheet_path=sheet_path,
                        center_x=center_x,
                        center_y=center_y
                    ))
                    match_count += 1
            except Exception as e:
                print(f"Error searching sheet {sheet['name']}: {str(e)}")
                raise
        
        print(f"Search complete for opening number '{number}' - Found {match_count} potential matches")
        return locations

    def process_task_locations(self, project_id, task_service, user_id):
        print("\n=== Processing Task Locations ===")
        if not isinstance(user_id, int):
            print("Error: user_id must be an integer")
            return
            
        # Initialize tkinter root for directory selection
        root = tk.Tk()
        root.withdraw()  # Hide the main window
        
        # Prompt user for save directory
        print("\nSelect directory to save match preview images:")
        save_dir = filedialog.askdirectory(title="Select Directory to Save Preview Images")
        if not save_dir:
            print("No directory selected. Exiting.")
            root.destroy()
            return
        print(f"Images will be saved to: {save_dir}")
        
        # Create a subfolder for sheet files
        sheets_dir = os.path.join(save_dir, "sheet_files")
        if not os.path.exists(sheets_dir):
            os.makedirs(sheets_dir)
            print(f"Sheet files will be saved to: {sheets_dir}")
        
        # Prompt user for task selection type
        print("\nChoose which UCI tasks to process:")
        print("  - Type 'all' to process all UCI tasks")
        print("  - Type 'unpositioned' to process only UCI tasks without positions")
        task_selection = input("Enter your choice: ").strip().lower()
        while task_selection not in ['all', 'unpositioned']:
            print("Invalid choice. Please enter 'all' or 'unpositioned'.")
            task_selection = input("Enter your choice: ").strip().lower()
        
        # Destroy the root window to avoid conflicts with PreviewWindow
        root.destroy()
            
        current_distance = 30
        print("\nRetrieving tasks...")
        tasks = task_service.get_all_tasks_in_project(project_id, filter_option='active')
        def_tasks, fc_tasks, uci_tasks, uca_tasks = self._create_task_maps(tasks)
        
        if task_selection == 'all':
            tasks_to_process = uci_tasks
            print(f"\nProcessing all {len(uci_tasks)} UCI tasks")
        else:  # unpositioned
            tasks_to_process = {}
            for number, task in uci_tasks.items():
                pos_x = task.get('pos_x')
                pos_y = task.get('pos_y')
                if (pos_x is None or pos_x == 0) and (pos_y is None or pos_y == 0):
                    tasks_to_process[number] = task
            print(f"\nProcessing {len(tasks_to_process)} unpositioned UCI tasks")
        
        if not tasks_to_process:
            print("No UCI tasks found to process. Exiting.")
            return
            
        print("\nRetrieving sheets...")
        sheets = self.get_all_sheets_in_project(project_id)
        print(f"Found {len(sheets)} active sheets")
        if not sheets:
            print("No active sheets found. Exiting.")
            return
            
        print("\nPreparing sheets for processing...")
        with ThreadPoolExecutor(max_workers=10) as executor:
            # Pass the sheets_dir to the _download_sheets_parallel method
            sheet_future = executor.submit(self._download_sheets_parallel, project_id, sheets, sheets_dir)
            sheet_paths = sheet_future.result()
            if not sheet_paths:
                print("Failed to download any sheets. Exiting.")
                return
                
            print("\nSheets ready. Starting task processing...")
            print("\n📋 USER INTERFACE INFO:")
            print("  • GUI buttons and keyboard shortcuts are both available")  
            print("  • Keyboard shortcuts: Click preview window first, then press keys")
            print("  • ON mode: Multiple related tasks with spacing controls")
            print("  • Next Match (n): Cycles through all matches for current opening number")
            print("  • Skip (s): Skips entire opening number and moves to next task")
            print("="*60)
            
            task_items = list(tasks_to_process.items())
            
            # Create a larger queue to store more search results
            results_queue = queue.Queue(maxsize=100)  # Increased from 50 to 100
            
            # Create a queue for task location updates
            update_queue = queue.Queue()
            
            # Create a set to track which numbers have been searched
            searched_numbers = set()
            
            # Create a set to track tasks that have been updated
            updated_tasks = set()
            
            # Create a threading event to signal the background threads to stop
            stop_event = threading.Event()
            
            # Add counters for progress reporting
            search_completed_count = 0
            update_completed_count = 0
            
            # Modified background searcher function that continuously searches
            def continuous_background_searcher():
                nonlocal search_completed_count
                task_index = 0
                last_progress_time = time.time()
                last_task_processed_time = time.time()
                search_status = "running"
                
                try:
                    print(f"\nStarting background search for {len(task_items)} opening numbers across {len(sheets)} sheets")
                    
                    while not stop_event.is_set() and task_index < len(task_items):
                        # Print periodic progress updates regardless of activity
                        current_time = time.time()
                        # Check if we've been stuck for too long (over 5 minutes without progress)
                        if current_time - last_task_processed_time > 300:  # 5 minutes
                            print(f"\nWARNING: No search progress for 5 minutes. Last processed task index: {task_index}/{len(task_items)}")
                            print(f"Current search status: {search_status}")
                            print("Attempting to continue...")
                            # Reset the timer to avoid repeated warnings
                            last_task_processed_time = current_time
                            
                        if current_time - last_progress_time > 5:  # Every 5 seconds
                            print(f"\rBackground search progress: {search_completed_count}/{len(task_items)} completed ({search_completed_count/len(task_items)*100:.1f}%), Queue size: {results_queue.qsize()}/{results_queue.maxsize}, Cache size: {len(cached_results)}", end="")
                            last_progress_time = current_time
                            
                        number, _ = task_items[task_index]
                        
                        # Skip if this number has already been searched
                        if number in searched_numbers:
                            task_index += 1
                            last_task_processed_time = time.time()  # Update last processed time
                            continue
                        
                        search_status = f"searching for '{number}'"
                        try:
                            # Search for this number
                            locations = self._search_number_across_sheets_with_rate_limit(
                                executor, project_id, sheets, sheet_paths, number, api_limit=10
                            )
                            
                            # Put the result in the queue, but don't block indefinitely
                            # if the queue is full (which means the user is way behind in processing)
                            try:
                                search_status = f"adding '{number}' to queue"
                                results_queue.put((number, locations), block=True, timeout=1)
                                # Only add to searched_numbers after successfully adding to queue
                                searched_numbers.add(number)
                                # Move to the next task
                                task_index += 1
                                search_completed_count += 1
                                last_task_processed_time = time.time()  # Update last processed time
                                # Update the last progress time
                                last_progress_time = time.time()
                            except queue.Full:
                                # If the queue is full, mark this number as "searched too far ahead"
                                # and move on to the next one instead of getting stuck in a loop
                                # We'll cache the results so they can be retrieved later
                                search_status = f"caching '{number}' (queue full)"
                                print(f"\nQueue full, caching results for opening number {number} and moving on")
                                cached_results[number] = locations
                                searched_numbers.add(number)
                                task_index += 1
                                search_completed_count += 1
                                last_task_processed_time = time.time()  # Update last processed time
                                # Update the last progress time
                                last_progress_time = time.time()
                                continue
                            
                        except Exception as e:
                            search_status = f"error with '{number}': {str(e)}"
                            print(f"\nError searching for opening number {number}: {str(e)}")
                            # Even on error, move to the next task but don't add to searched_numbers
                            task_index += 1
                            last_task_processed_time = time.time()  # Update last processed time
                    
                    # Final progress report
                    if task_index >= len(task_items):
                        search_status = "completed"
                        print(f"\nBackground search completed: {search_completed_count}/{len(task_items)} items processed")
                    else:
                        search_status = "stopped by user"
                        print(f"\nBackground search stopped: {search_completed_count}/{len(task_items)} items processed")
                
                except Exception as e:
                    search_status = f"failed with error: {str(e)}"
                    print(f"\nBackground search thread encountered an unhandled error: {str(e)}")
                    import traceback
                    traceback.print_exc()
                
                print(f"\nSearch thread status: {search_status} (Completed: {search_completed_count}/{len(task_items)})")
                
            # Add a monitor thread that periodically checks and reports the overall status
            def monitor_thread():
                last_search_count = 0
                last_update_count = 0
                last_check_time = time.time()
                monitor_interval = 30  # Check every 30 seconds
                
                while not stop_event.is_set():
                    time.sleep(monitor_interval)
                    current_time = time.time()
                    
                    # Skip if just started
                    if current_time - last_check_time < monitor_interval:
                        continue
                    
                    # Check for progress in both threads
                    search_progress = search_completed_count - last_search_count
                    update_progress = update_completed_count - last_update_count
                    
                    # Calculate rates
                    time_diff = current_time - last_check_time
                    search_rate = search_progress / time_diff * 60 if time_diff > 0 else 0  # per minute
                    update_rate = update_progress / time_diff * 60 if time_diff > 0 else 0  # per minute
                    
                    # Print status report
                    print("\n" + "="*70)
                    print(f"STATUS REPORT (after {time_diff:.1f} seconds):")
                    print(f"Search: {search_completed_count}/{len(task_items)} ({search_completed_count/len(task_items)*100:.1f}%) - Rate: {search_rate:.1f} items/min")
                    print(f"Updates: {update_completed_count} completed, {update_queue.qsize()} pending - Rate: {update_rate:.1f} items/min")
                    print(f"Results queue: {results_queue.qsize()}/{results_queue.maxsize} items")
                    print(f"Cache: {len(cached_results)} items")
                    
                    # Report potential issues
                    if search_progress == 0 and search_completed_count < len(task_items):
                        print("WARNING: Search appears to be stalled - no progress since last check")
                    
                    if update_progress == 0 and update_queue.qsize() > 0:
                        print("WARNING: Updates appear to be stalled with pending items")
                    
                    if results_queue.full():
                        print("NOTE: Results queue is full - items being cached instead")
                    
                    print("="*70)
                    
                    # Update for next check
                    last_search_count = search_completed_count
                    last_update_count = update_completed_count
                    last_check_time = current_time
            
            # Start the background search thread
            search_thread = threading.Thread(target=continuous_background_searcher)
            search_thread.daemon = True
            search_thread.start()
            
            # Task update worker thread function
            def task_update_worker():
                nonlocal update_completed_count
                last_update_time = time.time()
                last_status_time = time.time()
                update_status = "running"
                task_retry_counts = {}  # Track retry counts for each task
                max_task_retries = 3    # Maximum retries per task
                
                try:
                    print("\nStarting task update background worker")
                    
                    # Continue processing as long as there are items in the queue, even if stop_event is set
                    while not (stop_event.is_set() and update_queue.empty()):
                        current_time = time.time()
                        
                        # Check if we've been idle for too long (5 minutes) with pending updates
                        if current_time - last_update_time > 300 and update_queue.qsize() > 0:
                            pending = update_queue.qsize()
                            print(f"\nWARNING: Update worker idle for 5 minutes with {pending} pending updates")
                            print(f"Current update status: {update_status}")
                            print("Attempting to continue processing...")
                            # Reset timer to avoid repeated warnings
                            last_update_time = current_time
                            
                        # Periodically report update status
                        if current_time - last_status_time > 10:  # Every 10 seconds
                            if update_queue.qsize() > 0:
                                print(f"\rUpdate worker status: {update_completed_count} tasks updated, {update_queue.qsize()} pending", end="")
                                # If stop event is set but we still have tasks, note that we're finishing
                                if stop_event.is_set():
                                    print(f" (finishing final tasks)", end="")
                            last_status_time = current_time
                            
                        try:
                            # Get an update task from the queue with a timeout
                            # Use a shorter timeout if stop_event is set
                            timeout = 0.5 if stop_event.is_set() else 1.0
                            update_task = update_queue.get(timeout=timeout)
                            
                            # If we're stopping, print that we're processing a final task
                            if stop_event.is_set():
                                print("\nProcessing final task from queue before stopping")
                            
                            # Unpack the update task
                            (
                                update_number, 
                                uci_task_id, 
                                related_tasks, 
                                sheet, 
                                center_x, 
                                center_y, 
                                current_distance, 
                                user_id,
                                sheet_path,
                                task_positions,
                                save_dir
                            ) = update_task
                            
                            # Track retry count for this task
                            if update_number not in task_retry_counts:
                                task_retry_counts[update_number] = 0
                            
                            update_status = f"updating '{update_number}'"
                            print(f"\nProcessing update for opening number {update_number} on sheet {sheet['name']}")
                            
                            try:
                                # Update the UCI task location with retry handling
                                retry_attempts = 0
                                max_attempts = 3
                                success = False
                                
                                while retry_attempts < max_attempts and not success:
                                    try:
                                        updated_task = self.update_task_location(
                                            project_id=project_id,
                                            task_id=uci_task_id,
                                            floorplan_id=sheet['floorplan_id'],
                                            pos_x=center_x,
                                            pos_y=center_y,
                                            last_editor_user_id=user_id
                                        )
                                        
                                        if updated_task:
                                            success = True
                                        else:
                                            print(f"Attempt {retry_attempts+1}/{max_attempts} failed. Retrying...")
                                            retry_attempts += 1
                                            time.sleep(1)  # Brief delay before retry
                                    except Exception as e:
                                        print(f"Error on attempt {retry_attempts+1}/{max_attempts}: {str(e)}")
                                        retry_attempts += 1
                                        time.sleep(1)  # Brief delay before retry
                                
                                if success:
                                    # Save preview image with yes_ prefix in the background
                                    if save_dir:
                                        try:
                                            self._save_preview_image(
                                                sheet_path=sheet_path,
                                                center_x=center_x,
                                                center_y=center_y,
                                                number=update_number,
                                                save_dir=save_dir,
                                                task_positions=task_positions,
                                                filename_prefix=f"yes_{update_number}"
                                            )
                                            print(f"Preview image saved for accepted match: yes_{update_number}.jpg")
                                        except Exception as e:
                                            print(f"Error saving preview image: {str(e)}")
                                    
                                    # Add positions for related tasks if they exist
                                    related_positions = {
                                        'DEF': {'x': center_x - current_distance, 'y': center_y},  # Left
                                        'FC': {'x': center_x + current_distance, 'y': center_y},   # Right
                                        'UCA': {'x': center_x, 'y': center_y + current_distance}   # Bottom
                                    }
                                    
                                    # Update related task locations
                                    related_count = 0
                                    for task_type, related_task in related_tasks:
                                        if related_task:
                                            pos = related_positions[task_type]
                                            try:
                                                # Try up to 3 times for each related task
                                                for attempt in range(3):
                                                    try:
                                                        updated_related = self.update_task_location(
                                                            project_id=project_id,
                                                            task_id=related_task['id'],
                                                            floorplan_id=sheet['floorplan_id'],
                                                            pos_x=pos['x'],
                                                            pos_y=pos['y'],
                                                            last_editor_user_id=user_id
                                                        )
                                                        if updated_related:
                                                            print(f"{task_type} task location updated successfully")
                                                            related_count += 1
                                                            break  # Success, exit retry loop
                                                        else:
                                                            print(f"Failed to update {task_type} task location (attempt {attempt+1}/3)")
                                                            if attempt < 2:  # Only sleep if we're going to retry
                                                                time.sleep(1)
                                                    except Exception as e:
                                                        print(f"Error updating {task_type} task on attempt {attempt+1}: {str(e)}")
                                                        if attempt < 2:  # Only sleep if we're going to retry
                                                            time.sleep(1)
                                            except Exception as e:
                                                print(f"Error updating {task_type} task location: {str(e)}")
                                    
                                    # Add task to the updated tasks set
                                    updated_tasks.add(update_number)
                                    update_completed_count += 1
                                    last_update_time = time.time()  # Track successful updates
                                    
                                    # Print detailed completion message
                                    print(f"\nCompleted update for opening number {update_number}")
                                    print(f"Updated {related_count} related task(s)")
                                    print(f"Task updates processed: {update_completed_count}, Pending: {update_queue.qsize()}")
                                else:
                                    # All retries failed
                                    print(f"Failed to update UCI task {update_number} after {max_attempts} attempts")
                                    task_retry_counts[update_number] += 1
                                    
                                    if task_retry_counts[update_number] < max_task_retries:
                                        print(f"Will retry entire task later (attempt {task_retry_counts[update_number]+1}/{max_task_retries})")
                                        # Put task back in queue for later retry
                                        update_queue.put(update_task)
                                    else:
                                        print(f"Giving up on task {update_number} after {max_task_retries} full retries")
                                
                            except Exception as e:
                                update_status = f"error updating '{update_number}': {str(e)}"
                                print(f"\nError updating locations for opening number {update_number}: {str(e)}")
                                
                                # Increment retry count and decide if we should retry later
                                task_retry_counts[update_number] += 1
                                if task_retry_counts[update_number] < max_task_retries:
                                    print(f"Will retry task {update_number} later (attempt {task_retry_counts[update_number]+1}/{max_task_retries})")
                                    update_queue.put(update_task)
                                else:
                                    print(f"Giving up on task {update_number} after {max_task_retries} retries")
                            
                            # Mark the task as done in the queue if we're not retrying
                            if success or task_retry_counts.get(update_number, 0) >= max_task_retries:
                                update_queue.task_done()
                        
                        except queue.Empty:
                            # Queue is empty, just continue the loop
                            update_status = "idle - waiting for tasks"
                            continue
                        except Exception as e:
                            update_status = f"error in task processing: {str(e)}"
                            print(f"\nError in task update worker: {str(e)}")
                            
                            # Try to mark the task as done to avoid deadlock
                            try:
                                update_queue.task_done()
                            except Exception:
                                pass
                    
                    print(f"\nUpdate worker stopped: {update_completed_count} tasks processed")
                    
                except Exception as e:
                    update_status = f"failed with error: {str(e)}"
                    print(f"\nUpdate worker thread encountered an unhandled error: {str(e)}")
                    import traceback
                    traceback.print_exc()
                
                print(f"\nUpdate thread status: {update_status} (Completed: {update_completed_count})")
            
            # Start the task update worker thread
            update_thread = threading.Thread(target=task_update_worker)
            update_thread.daemon = True
            update_thread.start()
            
            # Start the monitor thread
            monitor_thread = threading.Thread(target=monitor_thread)
            monitor_thread.daemon = True
            monitor_thread.start()
            
            # Dictionary to store results for numbers that might be processed out of order
            cached_results = {}
            
            current_task_index = 0
            total_tasks = len(task_items)
            remaining_tasks = total_tasks
            out_of_order_count = 0  # Count consecutive out-of-order results
            max_out_of_order = 5  # Maximum consecutive out-of-order results before skipping ahead
            
            while current_task_index < len(task_items):
                # Process tkinter events to keep UI responsive
                process_events()
                
                number, uci_task = task_items[current_task_index]
                
                # Skip if this task has already been updated
                if number in updated_tasks:
                    print(f"\nSkipping task: {uci_task['name']} (already updated)")
                    current_task_index += 1
                    remaining_tasks -= 1
                    continue
                
                print("\n" + "="*50)
                print(f"Processing task: {uci_task['name']}")
                print(f"Remaining opening numbers to process: {remaining_tasks}")
                print(f"Search progress: {search_completed_count}/{len(task_items)}, Update progress: {update_completed_count}/{len(updated_tasks) + update_queue.qsize()}")
                print("="*50)
                
                # Check if we already have cached results for this number
                if number in cached_results:
                    print(f"Using cached results for opening number {number}")
                    result_number = number
                    locations = cached_results.pop(number)  # Remove from cache after retrieving
                    out_of_order_count = 0  # Reset the counter since we found a match
                else:
                    # If we've received too many out-of-order results in sequence, 
                    # we might be falling behind the background thread
                    if out_of_order_count >= max_out_of_order and len(cached_results) > 0:
                        # Find the nearest available cached result to skip ahead
                        nearest_index = float('inf')
                        nearest_number = None
                        
                        for cached_number in cached_results:
                            # Find this number in the task_items
                            for i, (task_number, _) in enumerate(task_items):
                                if task_number == cached_number and i > current_task_index:
                                    if i < nearest_index:
                                        nearest_index = i
                                        nearest_number = cached_number
                        
                        if nearest_number:
                            # Skip ahead to process this cached result
                            skipped_count = nearest_index - current_task_index
                            print(f"Falling behind background search - skipping ahead {skipped_count} tasks to {nearest_number}")
                            current_task_index = nearest_index
                            remaining_tasks -= skipped_count
                            out_of_order_count = 0
                            continue
                    
                    # Wait for the background thread to provide results
                    try:
                        # First check if we've received the result for this number already
                        if not number in searched_numbers:
                            print(f"Waiting for search results for opening number {number}...")
                        
                        # Use a smaller timeout and process events while waiting
                        wait_start = time.time()
                        result_received = False
                        
                        while not result_received and time.time() - wait_start < 60:  # 1-minute total timeout
                            try:
                                # Try to get results with a short timeout
                                result_number, locations = results_queue.get(timeout=0.5)
                                result_received = True
                            except queue.Empty:
                                # Process UI events while waiting
                                process_events()
                                # Short sleep to avoid CPU spinning
                                time.sleep(0.1)
                        
                        if not result_received:
                            print(f"Timeout waiting for search results for opening number {number}")
                            # If we time out, skip this number
                            current_task_index += 1
                            remaining_tasks -= 1
                            continue
                        
                        # If we got results for a different number, cache them for later
                        if result_number != number:
                            print(f"Received results for opening number {result_number} instead of {number} - caching for later")
                            cached_results[result_number] = locations
                            # Increment the out-of-order counter
                            out_of_order_count += 1
                            # Continue waiting for the right number
                            continue
                        else:
                            # Reset the counter since we found a match
                            out_of_order_count = 0
                    except Exception as e:
                        print(f"Error getting search results: {str(e)}")
                        # If we encounter an error, skip this number
                        current_task_index += 1
                        remaining_tasks -= 1
                        continue
                
                if not locations:
                    print(f"No locations found for opening number {number}")
                    remaining_tasks -= 1
                    current_task_index += 1
                    continue
                    
                location_found = False
                rejected_count = 0  # Counter for rejected matches for sequential filenames
                current_match_index = 0  # Track current match index for cycling
                skip_task = False  # Flag to skip to next task
                
                # Cycle through matches until user accepts one or skips the task
                while not location_found and not skip_task:
                    location = locations[current_match_index]
                    
                    # Modified to use new async update method
                    result = self._process_task_location_with_async_update(
                        project_id,
                        uci_task,
                        location.sheet,
                        location.center_x,
                        location.center_y,
                        def_tasks,
                        fc_tasks,
                        uca_tasks,
                        number,
                        current_distance,
                        user_id,
                        location.sheet_path,
                        save_dir,  # Pass save directory to the processing function
                        rejected_count,  # Pass the current rejected count
                        update_queue,  # Pass the update queue for async updates
                        match_number=current_match_index + 1,  # Pass current match number
                        total_matches=len(locations)  # Pass total matches
                    )
                    
                    if isinstance(result, tuple):
                        location_found, current_distance, was_rejected = result
                        if was_rejected:
                            rejected_count += 1
                            # Move to next match (cycle back to first if at end)
                            current_match_index = (current_match_index + 1) % len(locations)
                            print(f"Moving to match {current_match_index + 1} of {len(locations)} for opening number {number}")
                    elif result == True:
                        location_found = result
                    elif result == "skip_task":
                        # User pressed 's' to skip the entire task
                        skip_task = True
                        print(f"User skipped opening number {number} - moving to next task")
                    elif result == False:
                        # This shouldn't happen with the new logic, but handle it just in case
                        print(f"Unexpected result: {result}. Skipping task.")
                        skip_task = True
                
                # Save any remaining matches as rejected images (only if user accepted one match)
                if location_found:
                    for i, location in enumerate(locations):
                        if i != current_match_index:  # Skip the accepted match
                            try:
                                rejected_count += 1
                                self._save_preview_image(
                                    sheet_path=location.sheet_path,
                                    center_x=location.center_x,
                                    center_y=location.center_y,
                                    number=number,
                                    save_dir=save_dir,
                                    task_positions=[{
                                        'pos_x': location.center_x,
                                        'pos_y': location.center_y,
                                        'task_type': 'UCI',
                                        'is_main': True
                                    }],
                                    filename_prefix=f"no_{number}_{rejected_count}"
                                )
                                print(f"Saved rejected match image: no_{number}_{rejected_count}.jpg")
                            except Exception as e:
                                print(f"Error saving rejected match image: {str(e)}")
                        
                if location_found:
                    print(f"Successfully processed opening number {number} (Update in progress)")
                else:
                    print(f"No suitable location found for opening number {number}")
                    
                remaining_tasks -= 1
                current_task_index += 1
                
            # Before stopping the threads, make sure all queued updates have been processed
            print("\nAll tasks have been processed by user. Waiting for update queue to empty...")
            
            # Wait for queued updates to complete before stopping threads
            wait_start = time.time()
            wait_timeout = 30  # 30 seconds
            
            # If there are pending updates, wait for the queue to empty or timeout
            if not update_queue.empty():
                queue_size = update_queue.qsize()
                print(f"Waiting for {queue_size} pending updates to complete before stopping threads...")
                
                while not update_queue.empty() and time.time() - wait_start < wait_timeout:
                    # Process events to keep UI responsive
                    process_events()
                    
                    # Check progress
                    current_size = update_queue.qsize()
                    if current_size != queue_size:
                        print(f"Update progress: {current_size} updates remaining")
                        queue_size = current_size
                        # Reset timeout when making progress
                        wait_start = time.time()
                        
                    time.sleep(0.5)
                    
                if update_queue.empty():
                    print("All updates completed successfully before stopping threads")
                else:
                    print(f"Warning: {update_queue.qsize()} updates still pending, but proceeding")
            
            # Signal the background threads to stop
            print("Signaling background threads to stop...")
            stop_event.set()
            
            # Wait for the background threads to finish
            search_thread.join(timeout=5)
            update_thread.join(timeout=5)
            monitor_thread.join(timeout=5)
            
            # Final check to make sure everything was processed
            if update_queue.empty():
                print("\nSuccess: All task updates were completed before threads stopped")
            else:
                remaining = update_queue.qsize()
                print(f"\nWarning: {remaining} task updates were not processed before threads stopped")
                print("These tasks will be manually processed now.")
                
                # Use the direct processing method already implemented for the final timeout case
            
        print("\nTask location processing completed")

    def _process_task_location_with_async_update(
        self,
        project_id: str,
        uci_task: Dict,
        sheet: Dict,
        center_x: float,
        center_y: float,
        def_tasks: Dict,
        fc_tasks: Dict,
        uca_tasks: Dict,
        number: str,
        current_distance: int,
        user_id: int,
        sheet_path: str,
        save_dir: str = None,
        rejected_count: int = 0,
        update_queue: queue.Queue = None,
        match_number: int = 1,
        total_matches: int = 1
    ) -> Union[bool, Tuple[bool, int, bool]]:
        """Process a single task location with user interaction and async updates."""
        # Store the preview window reference for image saving
        preview_window = None
        
        while True:  # Loop for distance adjustment
            # Calculate positions for all related tasks
            task_positions = [
                {
                    'pos_x': center_x,
                    'pos_y': center_y,
                    'task_type': 'UCI',
                    'is_main': True
                }
            ]
            
            # Add positions for related tasks if they exist
            related_positions = {
                'DEF': {'x': center_x - current_distance, 'y': center_y},  # Left
                'FC': {'x': center_x + current_distance, 'y': center_y},   # Right
                'UCA': {'x': center_x, 'y': center_y + current_distance}   # Bottom
            }
            
            related_tasks = [
                ('DEF', def_tasks.get(number)),
                ('FC', fc_tasks.get(number)),
                ('UCA', uca_tasks.get(number))
            ]
            
            for task_type, related_task in related_tasks:
                if related_task:
                    pos = related_positions[task_type]
                    task_positions.append({
                        'pos_x': pos['x'],
                        'pos_y': pos['y'],
                        'task_type': task_type,
                        'is_main': False
                    })
            
            # Show preview with all task positions
            print(f"\n=========================================================")
            print(f"Found potential match on sheet {sheet['name']}")
            print(f"Current spacing: {current_distance} pixels")
            print(f"Opening Number: {number} (Match {match_number} of {total_matches})")
            print(f"Opening a preview window for user interaction...")
            print(f"Creating ON mode preview with distance controls ENABLED")
            print(f"=========================================================")
            
            # Create and show preview window with match information including sheet name and page number
            sheet_name = sheet.get('name', 'Unknown Sheet')
            page_number = sheet.get('page_number', 'Unknown')
            match_info = f"{number} (Match {match_number} of {total_matches}) - Sheet: {sheet_name} - Page: {page_number}"
            
            try:
                # Create the preview window - EXPLICITLY enable distance controls for ON mode
                preview_window = PreviewWindow(
                    image_url=f"file://{sheet_path}",
                    locations=task_positions,
                    current_distance=current_distance,
                    task_name=match_info,  # Show the opening number with match info
                    enable_distance_controls=True  # Explicitly enable for ON mode
                )
                
                # Show the window and wait for user input
                print("Waiting for user to interact with the preview window...")
                choice, new_distance = preview_window.show()
                print(f"User selected: {choice}, Distance changed from {current_distance} to {new_distance}")
                
                # Store the new distance
                current_distance = new_distance  # Update the current distance
                
                if current_distance != new_distance:
                    print(f"Distance was changed by user from {current_distance} to {new_distance}")
            except Exception as e:
                print(f"Error displaying preview window: {str(e)}")
                import traceback
                traceback.print_exc()
                return False
            
            # Handle directional movement
            if choice in ['up', 'down', 'left', 'right']:
                # Adjust center position by 10 pixels
                old_x, old_y = center_x, center_y
                if choice == 'up':
                    center_y -= 10
                elif choice == 'down':
                    center_y += 10
                elif choice == 'left':
                    center_x -= 10
                elif choice == 'right':
                    center_x += 10
                print(f"Adjusted position: ({old_x}, {old_y}) -> ({center_x}, {center_y})")
                continue  # Show preview again with new position
            
            # Note: BC mode does not support spacing adjustments (z/x keys are disabled)
            
            if choice == 'y':
                try:
                    if 'floorplan_id' not in sheet:
                        print("Error: Sheet is missing floorplan_id. Skipping this result.")
                        return False
                    
                    # Instead of updating immediately, add the task to the update queue
                    # and let the background thread handle it
                    if update_queue:
                        update_task = (
                            number,                # Opening number
                            uci_task['id'],        # UCI task ID
                            related_tasks,         # Related tasks
                            sheet,                 # Sheet
                            center_x,              # X coordinate
                            center_y,              # Y coordinate
                            current_distance,      # Current distance
                            user_id,               # User ID
                            sheet_path,            # Sheet path
                            task_positions,        # Task positions for image saving
                            save_dir               # Save directory
                        )
                        
                        # Add to the update queue
                        update_queue.put(update_task)
                        print("Task update queued - continuing to next task")
                        
                        # Return immediately to continue processing
                        return True, current_distance, False
                    else:  
                        # Fallback to synchronous update if no queue provided
                        print("Warning: No update queue available, performing synchronous update")
                        updated_task = self.update_task_location(
                            project_id=project_id,
                            task_id=uci_task['id'],
                            floorplan_id=sheet['floorplan_id'],
                            pos_x=center_x,
                            pos_y=center_y,
                            last_editor_user_id=user_id
                        )
                        
                        if not updated_task:
                            print("Failed to update UCI task location. Canceling sequence.")
                            return False
                            
                        # Save image and update related tasks
                        # ... synchronous code ...
                        return True
                except ValueError as e:
                    print(f"Error updating task location: {str(e)}")
                    print("Canceling sequence.")
                    return False
            elif choice == 's':
                # Skip the entire task (opening number) and move to next task
                if save_dir:
                    try:
                        # Save preview image with no_ prefix and sequence number
                        rejected_count += 1
                        self._save_preview_image(
                            sheet_path=sheet_path,
                            center_x=center_x,
                            center_y=center_y,
                            number=number,
                            save_dir=save_dir,
                            task_positions=task_positions,
                            filename_prefix=f"no_{number}_{rejected_count}"
                        )
                        print(f"Preview image saved for rejected match: no_{number}_{rejected_count}.jpg")
                    except Exception as e:
                        print(f"Error saving rejected match image: {str(e)}")
                return "skip_task"  # Special return value to indicate skipping entire task
            elif choice == 'n':
                # Go to next match and consider it rejected
                if save_dir:
                    try:
                        # Save preview image with no_ prefix and sequence number
                        rejected_count += 1
                        self._save_preview_image(
                            sheet_path=sheet_path,
                            center_x=center_x,
                            center_y=center_y,
                            number=number,
                            save_dir=save_dir,
                            task_positions=task_positions,
                            filename_prefix=f"no_{number}_{rejected_count}"
                        )
                        print(f"Preview image saved for rejected match: no_{number}_{rejected_count}.jpg")
                    except Exception as e:
                        print(f"Error saving rejected match image: {str(e)}")
                return False, current_distance, True  # Return that it was rejected
            elif choice in ['z', 'x']:
                # Handle distance adjustment keys
                print(f"Distance adjustment key '{choice}' pressed - position will be recalculated with new distance: {current_distance}")
                continue  # Show preview again with new distance
            else:
                print(f"User choice '{choice}' not recognized or window was closed. Skipping task.")
                return False

    def _create_task_maps(self, tasks: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        """Create task maps for different task types."""
        def_tasks: Dict[str, Dict[str, Any]] = {}
        fc_tasks: Dict[str, Dict[str, Any]] = {}
        uci_tasks: Dict[str, Dict[str, Any]] = {}
        uca_tasks: Dict[str, Dict[str, Any]] = {}
        
        for task in tasks:
            name = task['name']
            if not name:
                continue
                
            number = None
            if name.startswith("DEF "):
                number = name[4:].strip()
                def_tasks[number] = task
            elif name.startswith("FC "):
                number = name[3:].strip()
                fc_tasks[number] = task
            elif name.startswith("UCI "):
                number = name[4:].strip()
                uci_tasks[number] = task
            elif name.startswith("UCA "):
                number = name[4:].strip()
                uca_tasks[number] = task
                
        return def_tasks, fc_tasks, uci_tasks, uca_tasks

    def _download_sheets_parallel(self, project_id: str, sheets: List[Dict[str, Any]], sheets_dir: str) -> Dict[str, str]:
        """Download sheets in parallel."""
        sheet_details: Dict[str, Dict[str, Any]] = {}
        
        def download_sheet(sheet: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, Any]]]:
            details = self.get_sheet_by_id(project_id, sheet['id'])
            if details and details.get('file_url'):
                return sheet['id'], details
            return None
            
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(download_sheet, sheet) for sheet in sheets]
            for future in futures:
                result = future.result()
                if result:
                    sheet_id, details = result
                    sheet_details[sheet_id] = details
        
        # Download all sheets in parallel and save to specified directory
        sheet_paths = download_sheets(sheet_details.values(), save_dir=sheets_dir)
        return sheet_paths 

    def _save_preview_image(self, sheet_path: str, center_x: float, center_y: float, number: str, save_dir: str, task_positions: List[Dict[str, Any]], filename_prefix: str = None):
        """Save a small 128x128 image centered exactly on the UCI task marker."""
        try:
            # Load the original full-resolution image
            image = Image.open(sheet_path)
            
            # Find the main UCI task's exact position to center on
            main_task = next((loc for loc in task_positions if loc.get('is_main')), None)
            if main_task:
                center_point_x = main_task['pos_x']
                center_point_y = main_task['pos_y']
            else:
                center_point_x = center_x
                center_point_y = center_y
            
            # Define crop size (128x128 pixels)
            crop_size = 128
            half_size = crop_size // 2
            
            # Calculate crop boundaries, ensuring we don't go outside the image bounds
            crop_x1 = max(0, int(center_point_x - half_size))
            crop_y1 = max(0, int(center_point_y - half_size))
            crop_x2 = min(image.width, int(center_point_x + half_size))
            crop_y2 = min(image.height, int(center_point_y + half_size))
            
            # Adjust crop dimensions if we hit image boundaries to maintain square ratio
            if crop_x2 - crop_x1 != crop_size:
                if crop_x1 == 0:  # Hit left boundary
                    crop_x2 = min(image.width, crop_x1 + crop_size)
                else:  # Hit right boundary
                    crop_x1 = max(0, crop_x2 - crop_size)
                    
            if crop_y2 - crop_y1 != crop_size:
                if crop_y1 == 0:  # Hit top boundary
                    crop_y2 = min(image.height, crop_y1 + crop_size)
                else:  # Hit bottom boundary
                    crop_y1 = max(0, crop_y2 - crop_size)
            
            # Crop the image at the original resolution
            cropped_image = image.crop((crop_x1, crop_y1, crop_x2, crop_y2))
            
            # Create filename
            if filename_prefix:
                # Use the specified prefix
                valid_filename = filename_prefix
            else:
                # Use the original naming convention
                valid_filename = ''.join(c if c.isalnum() or c in ('-', '_') else '_' for c in str(number))
                
            file_path = os.path.join(save_dir, f"{valid_filename}.jpg")
            
            # Save as high-quality JPEG
            cropped_image.save(file_path, "JPEG", quality=95)
            return file_path
        except Exception as e:
            print(f"Error saving preview image: {str(e)}")
            raise

    def _get_user_folder_selection(self, folders):
        """Get user selection for folder.
        
        Args:
            folders (list): List of folder objects
            
        Returns:
            str: Selected folder ID or None if cancelled
        """
        if not folders:
            print("No folders available.")
            return None
            
        print("\nAvailable Folders:")
        for i, folder in enumerate(folders, 1):
            name = folder.get('name', 'Unnamed')
            print(f"  {i}. {name}")
        
        while True:
            try:
                choice = input(f"\nSelect folder (1-{len(folders)}) or 'q' to quit: ").strip()
                if choice.lower() == 'q':
                    return None
                    
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(folders):
                    selected = folders[choice_idx]
                    print(f"Selected folder: {selected.get('name', 'Unnamed')}")
                    return selected['id']
                else:
                    print(f"Invalid choice. Please enter a number between 1 and {len(folders)}.")
            except ValueError:
                print("Invalid input. Please enter a number.")

    def _get_user_floorplan_selection(self, floorplans):
        """Get user selection for floorplan.
        
        Args:
            floorplans (list): List of floorplan objects
            
        Returns:
            str: Selected floorplan ID or None if cancelled
        """
        if not floorplans:
            print("No floorplans available.")
            return None
            
        print("\nAvailable Floorplans:")
        for i, floorplan in enumerate(floorplans, 1):
            name = floorplan.get('name', 'Unnamed')
            print(f"  {i}. {name}")
        
        while True:
            try:
                choice = input(f"\nSelect floorplan (1-{len(floorplans)}) or 'q' to quit: ").strip()
                if choice.lower() == 'q':
                    return None
                    
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(floorplans):
                    selected = floorplans[choice_idx]
                    print(f"Selected floorplan: {selected.get('name', 'Unnamed')}")
                    return selected['id']
                else:
                    print(f"Invalid choice. Please enter a number between 1 and {len(floorplans)}.")
            except ValueError:
                print("Invalid input. Please enter a number.")

    def _get_user_team_selection(self, teams):
        """Get user selection for team.
        
        Args:
            teams (list): List of team objects
            
        Returns:
            str: Selected team ID or None if cancelled
        """
        if not teams:
            print("No teams available.")
            return None
            
        print("\nAvailable Teams:")
        for i, team in enumerate(teams, 1):
            name = team.get('name', 'Unnamed')
            print(f"  {i}. {name}")
        
        while True:
            try:
                choice = input(f"\nSelect team (1-{len(teams)}) or 'q' to quit: ").strip()
                if choice.lower() == 'q':
                    return None
                    
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(teams):
                    selected = teams[choice_idx]
                    print(f"Selected team: {selected.get('name', 'Unnamed')}")
                    return selected['id']
                else:
                    print(f"Invalid choice. Please enter a number between 1 and {len(teams)}.")
            except ValueError:
                print("Invalid input. Please enter a number.")

    def _create_bc_task_map(self, tasks, selected_team_id):
        """Create task map for BC mode filtering by team ID.
        
        Args:
            tasks (list): List of all tasks
            selected_team_id (str): ID of the selected team
            
        Returns:
            dict: Task map with task name as key and task object as value
        """
        bc_tasks = {}
        
        for task in tasks:
            # Filter by team ID
            if task.get('team_id') == selected_team_id:
                name = task.get('name')
                if name:
                    bc_tasks[name] = task
                    
        print(f"Found {len(bc_tasks)} tasks in selected team")
        return bc_tasks

    def bc_process_task_locations(self, project_id, task_service, user_id):
        """Process task locations for BC mode (British Columbia).
        
        BC mode differences from ON mode:
        - User selects a specific folder to filter sheets
        - User selects a team to filter tasks  
        - Only one task per opening number (no related tasks)
        - No distance adjustments between tasks
        - Search uses exact task names (no prefix removal)
        """
        print("\n=== BC Processing Task Locations ===")
        if not isinstance(user_id, int):
            print("Error: user_id must be an integer")
            return
        
        # Initialize tkinter root for directory selection
        root = tk.Tk()
        root.withdraw()  # Hide the main window
        
        # Prompt user for save directory
        print("\nSelect directory to save match preview images:")
        save_dir = filedialog.askdirectory(title="Select Directory to Save Preview Images")
        if not save_dir:
            print("No directory selected. Exiting.")
            root.destroy()
            return
        print(f"Images will be saved to: {save_dir}")
        
        # Create a subfolder for sheet files
        sheets_dir = os.path.join(save_dir, "sheet_files")
        if not os.path.exists(sheets_dir):
            os.makedirs(sheets_dir)
            print(f"Sheet files will be saved to: {sheets_dir}")
        
        # Destroy the root window to avoid conflicts with PreviewWindow
        root.destroy()
        
        # BC Mode: Get folder and team selection
        from services.attribute import AttributeService
        attribute_service = AttributeService(self.bearer_token)
        
        # Get folders
        print("\nRetrieving folders...")
        folders = self.get_all_folders_in_project(project_id)
        if not folders:
            print("No folders found. Exiting.")
            return
        
        # Get user folder selection
        selected_folder_id = self._get_user_folder_selection(folders)
        if not selected_folder_id:
            print("No folder selected. Exiting.")
            return
        
        # Debug: Show selected folder details
        selected_folder = next((f for f in folders if f['id'] == selected_folder_id), None)
        if selected_folder:
            print(f"Selected folder: {selected_folder.get('name', 'Unnamed')} (ID: {selected_folder_id})")
        
        # Get teams
        print("\nRetrieving teams...")
        teams = attribute_service.get_all_teams_in_project(project_id)
        if not teams:
            print("No teams found. Exiting.")
            return
        
        # Get user team selection
        selected_team_id = self._get_user_team_selection(teams)
        if not selected_team_id:
            print("No team selected. Exiting.")
            return
        
        # Get sheets filtered by folder
        print(f"\nRetrieving sheets for selected folder...")
        sheets = self.get_all_sheets_in_project(project_id, filter_option='active', folder_id=selected_folder_id)
        print(f"Found {len(sheets)} sheets for selected folder")
        
        # Debug: Show which sheets were retrieved
        print("\nSheets in selected folder:")
        for i, sheet in enumerate(sheets, 1):
            sheet_name = sheet.get('name', 'Unnamed')
            sheet_id = sheet.get('id', 'Unknown')
            folder_id = sheet.get('folder_id', 'None')
            print(f"  {i}. {sheet_name} (ID: {sheet_id}, Folder ID: {folder_id})")
        
        if not sheets:
            print("No sheets found for selected folder. Exiting.")
            return
        
        # Get tasks and create BC task map
        print("\nRetrieving tasks...")
        tasks = task_service.get_all_tasks_in_project(project_id, filter_option='active')
        bc_tasks = self._create_bc_task_map(tasks, selected_team_id)
        
        # Prompt user for task selection type
        print(f"\nChoose which tasks from the selected team to process:")
        print("  - Type 'all' to process all tasks in the team")
        print("  - Type 'unpositioned' to process only tasks without positions")
        task_selection = input("Enter your choice: ").strip().lower()
        while task_selection not in ['all', 'unpositioned']:
            print("Invalid choice. Please enter 'all' or 'unpositioned'.")
            task_selection = input("Enter your choice: ").strip().lower()
        
        if task_selection == 'all':
            tasks_to_process = bc_tasks
            print(f"\nProcessing all {len(bc_tasks)} tasks in selected team")
        else:  # unpositioned
            tasks_to_process = {}
            for name, task in bc_tasks.items():
                pos_x = task.get('pos_x')
                pos_y = task.get('pos_y')
                if (pos_x is None or pos_x == 0) and (pos_y is None or pos_y == 0):
                    tasks_to_process[name] = task
            print(f"\nProcessing {len(tasks_to_process)} unpositioned tasks in selected team")
        
        if not tasks_to_process:
            print("No tasks found to process. Exiting.")
            return
        
        print("\nPreparing sheets for processing...")
        with ThreadPoolExecutor(max_workers=10) as executor:
            # Download sheets in parallel
            sheet_future = executor.submit(self._download_sheets_parallel, project_id, sheets, sheets_dir)
            sheet_paths = sheet_future.result()
            if not sheet_paths:
                print("Failed to download any sheets. Exiting.")
                return
                
            print("\nSheets ready. Starting BC task processing...")
            print("\n📋 USER INTERFACE INFO:")
            print("  • GUI buttons and keyboard shortcuts are both available")  
            print("  • Keyboard shortcuts: Click preview window first, then press keys")
            print("  • BC mode: No spacing controls (single task per location)")
            print("="*60)
            
            task_items = list(tasks_to_process.items())
            
            # Create queues for BC processing
            results_queue = queue.Queue(maxsize=100)
            update_queue = queue.Queue()
            searched_numbers = set()
            updated_tasks = set()
            stop_event = threading.Event()
            
            # Progress counters
            search_completed_count = 0
            update_completed_count = 0
            
            # BC Background searcher function
            def bc_background_searcher():
                nonlocal search_completed_count
                task_index = 0
                last_progress_time = time.time()
                last_task_processed_time = time.time()
                search_status = "running"
                
                try:
                    print(f"\nStarting BC background search for {len(task_items)} tasks across {len(sheets)} sheets")
                    
                    while not stop_event.is_set() and task_index < len(task_items):
                        current_time = time.time()
                        
                        # Progress monitoring
                        if current_time - last_task_processed_time > 300:  # 5 minutes
                            print(f"\nWARNING: No search progress for 5 minutes. Last processed task index: {task_index}/{len(task_items)}")
                            print(f"Current search status: {search_status}")
                            print("Attempting to continue...")
                            last_task_processed_time = current_time
                            
                        if current_time - last_progress_time > 5:  # Every 5 seconds
                            print(f"\rBC search progress: {search_completed_count}/{len(task_items)} completed ({search_completed_count/len(task_items)*100:.1f}%), Queue size: {results_queue.qsize()}/{results_queue.maxsize}, Cache size: {len(cached_results)}", end="")
                            last_progress_time = current_time
                            
                        task_name, _ = task_items[task_index]
                        
                        # Skip if already searched
                        if task_name in searched_numbers:
                            task_index += 1
                            last_task_processed_time = time.time()
                            continue
                        
                        search_status = f"searching for '{task_name}'"
                        try:
                            # Search for this task name (exact match, no prefix removal)
                            locations = self._search_number_across_sheets_with_rate_limit(
                                executor, project_id, sheets, sheet_paths, task_name, api_limit=10
                            )
                            
                            # Add to queue or cache
                            try:
                                search_status = f"adding '{task_name}' to queue"
                                results_queue.put((task_name, locations), block=True, timeout=1)
                                searched_numbers.add(task_name)
                                task_index += 1
                                search_completed_count += 1
                                last_task_processed_time = time.time()
                                last_progress_time = time.time()
                            except queue.Full:
                                search_status = f"caching '{task_name}' (queue full)"
                                print(f"\nQueue full, caching results for task {task_name} and moving on")
                                cached_results[task_name] = locations
                                searched_numbers.add(task_name)
                                task_index += 1
                                search_completed_count += 1
                                last_task_processed_time = time.time()
                                last_progress_time = time.time()
                        except Exception as e:
                            search_status = f"error with '{task_name}': {str(e)}"
                            print(f"\nError searching for task {task_name}: {str(e)}")
                            task_index += 1
                            last_task_processed_time = time.time()
                    
                    # Final progress report
                    if task_index >= len(task_items):
                        search_status = "completed"
                        print(f"\nBC background search completed: {search_completed_count}/{len(task_items)} items processed")
                    else:
                        search_status = "stopped by user"
                        print(f"\nBC background search stopped: {search_completed_count}/{len(task_items)} items processed")
                
                except Exception as e:
                    search_status = f"failed with error: {str(e)}"
                    print(f"\nBC background search thread encountered an unhandled error: {str(e)}")
                    import traceback
                    traceback.print_exc()
                
                print(f"\nBC search thread status: {search_status} (Completed: {search_completed_count}/{len(task_items)})")
            
            # BC Task update worker
            def bc_task_update_worker():
                nonlocal update_completed_count
                last_update_time = time.time()
                last_status_time = time.time()
                update_status = "running"
                
                try:
                    print("\nStarting BC task update background worker")
                    
                    while not stop_event.is_set():
                        current_time = time.time()
                        
                        # Idle monitoring
                        if current_time - last_update_time > 300 and update_queue.qsize() > 0:
                            pending = update_queue.qsize()
                            print(f"\nWARNING: BC update worker idle for 5 minutes with {pending} pending updates")
                            print(f"Current update status: {update_status}")
                            print("Attempting to continue processing...")
                            last_update_time = current_time
                            
                        # Status reporting
                        if current_time - last_status_time > 10:  # Every 10 seconds
                            if update_queue.qsize() > 0:
                                print(f"\rBC update worker status: {update_completed_count} tasks updated, {update_queue.qsize()} pending", end="")
                            last_status_time = current_time
                            
                        try:
                            # Get update task from queue
                            update_task = update_queue.get(timeout=1)
                            
                            # Unpack BC update task (simpler than ON mode)
                            (
                                task_name,
                                task_id, 
                                sheet, 
                                center_x, 
                                center_y, 
                                user_id,
                                sheet_path,
                                task_position,
                                save_dir
                            ) = update_task
                            
                            update_status = f"updating '{task_name}'"
                            print(f"\nProcessing BC update for task {task_name} on sheet {sheet['name']}")
                            
                            try:
                                # Update the task location
                                updated_task = self.update_task_location(
                                    project_id=project_id,
                                    task_id=task_id,
                                    floorplan_id=sheet['floorplan_id'],
                                    pos_x=center_x,
                                    pos_y=center_y,
                                    last_editor_user_id=user_id
                                )
                                
                                if updated_task:
                                    # Save preview image
                                    if save_dir:
                                        try:
                                            self._save_preview_image(
                                                sheet_path=sheet_path,
                                                center_x=center_x,
                                                center_y=center_y,
                                                number=task_name,
                                                save_dir=save_dir,
                                                task_positions=[task_position],
                                                filename_prefix=f"yes_{task_name}"
                                            )
                                            print(f"Preview image saved for accepted BC match: yes_{task_name}.jpg")
                                        except Exception as e:
                                            print(f"Error saving preview image: {str(e)}")
                                    
                                    # Track completion
                                    updated_tasks.add(task_name)
                                    update_completed_count += 1
                                    last_update_time = time.time()
                                    
                                    print(f"\nCompleted BC update for task {task_name}")
                                    print(f"BC updates processed: {update_completed_count}, Pending: {update_queue.qsize()}")
                                    
                            except Exception as e:
                                update_status = f"error updating '{task_name}': {str(e)}"
                                print(f"\nError updating BC task location for {task_name}: {str(e)}")
                            
                            # Mark task as done
                            update_queue.task_done()
                        
                        except queue.Empty:
                            update_status = "idle - waiting for tasks"
                            continue
                        except Exception as e:
                            update_status = f"error in task processing: {str(e)}"
                            print(f"\nError in BC task update worker: {str(e)}")
                    
                    print(f"\nBC update worker stopped: {update_completed_count} tasks processed")
                    
                except Exception as e:
                    update_status = f"failed with error: {str(e)}"
                    print(f"\nBC update worker thread encountered an unhandled error: {str(e)}")
                    import traceback
                    traceback.print_exc()
                
                print(f"\nBC update thread status: {update_status} (Completed: {update_completed_count})")
            
            # Start background threads
            search_thread = threading.Thread(target=bc_background_searcher)
            search_thread.daemon = True
            search_thread.start()
            
            update_thread = threading.Thread(target=bc_task_update_worker)
            update_thread.daemon = True
            update_thread.start()
            
            # Main processing loop for BC mode
            cached_results = {}
            current_task_index = 0
            total_tasks = len(task_items)
            remaining_tasks = total_tasks
            out_of_order_count = 0
            max_out_of_order = 5
            
            while current_task_index < len(task_items):
                # Process tkinter events to keep UI responsive
                process_events()
                
                task_name, task = task_items[current_task_index]
                
                # Skip if already updated
                if task_name in updated_tasks:
                    print(f"\nSkipping task: {task['name']} (already updated)")
                    current_task_index += 1
                    remaining_tasks -= 1
                    continue
                
                print("\n" + "="*50)
                print(f"Processing BC task: {task['name']}")
                print(f"Remaining tasks to process: {remaining_tasks}")
                print(f"Search progress: {search_completed_count}/{len(task_items)}, Update progress: {update_completed_count}")
                print("="*50)
                
                # Get results from cache or queue
                if task_name in cached_results:
                    print(f"Using cached results for task {task_name}")
                    result_name = task_name
                    locations = cached_results.pop(task_name)
                    out_of_order_count = 0
                else:
                    # Handle out-of-order results
                    if out_of_order_count >= max_out_of_order and len(cached_results) > 0:
                        # Skip ahead to nearest cached result
                        nearest_index = float('inf')
                        nearest_name = None
                        
                        for cached_name in cached_results:
                            for i, (item_name, _) in enumerate(task_items):
                                if item_name == cached_name and i > current_task_index:
                                    if i < nearest_index:
                                        nearest_index = i
                                        nearest_name = cached_name
                        
                        if nearest_name:
                            skipped_count = nearest_index - current_task_index
                            print(f"Falling behind BC search - skipping ahead {skipped_count} tasks to {nearest_name}")
                            current_task_index = nearest_index
                            remaining_tasks -= skipped_count
                            out_of_order_count = 0
                            continue
                    
                    # Wait for results from background thread
                    try:
                        if task_name not in searched_numbers:
                            print(f"Waiting for search results for task {task_name}...")
                        
                        # Use a smaller timeout and process events while waiting
                        wait_start = time.time()
                        result_received = False
                        
                        while not result_received and time.time() - wait_start < 60:  # 1-minute total timeout
                            try:
                                # Try to get results with a short timeout
                                result_name, locations = results_queue.get(timeout=0.5)
                                result_received = True
                            except queue.Empty:
                                # Process UI events while waiting
                                process_events()
                                # Short sleep to avoid CPU spinning
                                time.sleep(0.1)
                        
                        if not result_received:
                            print(f"Timeout waiting for search results for task {task_name}")
                            # If we time out, skip this task
                            current_task_index += 1
                            remaining_tasks -= 1
                            continue
                        
                        if result_name != task_name:
                            print(f"Received results for task {result_name} instead of {task_name} - caching for later")
                            cached_results[result_name] = locations
                            out_of_order_count += 1
                            continue
                        else:
                            out_of_order_count = 0
                    except Exception as e:
                        print(f"Error getting BC search results: {str(e)}")
                        current_task_index += 1
                        remaining_tasks -= 1
                        continue
                
                if not locations:
                    print(f"No locations found for task {task_name}")
                    remaining_tasks -= 1
                    current_task_index += 1
                    continue
                    
                # Debug: Show total matches found
                total_matches = len(locations)
                print(f"Found {total_matches} potential matches for task {task_name}")
                
                location_found = False
                rejected_count = 0
                current_match_index = 0
                
                # Loop through matches until user accepts one or skips
                matches_shown = set()  # Track which matches have been shown to prevent infinite loops
                
                while not location_found:
                    location = locations[current_match_index]
                    match_number = current_match_index + 1
                    
                    print(f"\nShowing match {match_number} of {total_matches} for task {task_name}")
                    
                    # Process the location with BC-specific handling
                    result = self._process_bc_task_location_with_async_update(
                        project_id,
                        task,
                        location.sheet,
                        location.center_x,
                        location.center_y,
                        task_name,
                        user_id,
                        location.sheet_path,
                        save_dir,
                        rejected_count,
                        update_queue,
                        match_number,  # Pass current match number
                        total_matches  # Pass total matches
                    )
                    
                    if isinstance(result, tuple):
                        action, was_rejected = result
                        if action == 'accepted':
                            location_found = True
                        elif action == 'skipped':
                            # User chose to skip this task entirely
                            print(f"Task {task_name} skipped by user")
                            break
                        elif action == 'next':
                            # User wants to see next match
                            if was_rejected:
                                rejected_count += 1
                                # Save rejected match image
                                try:
                                    self._save_preview_image(
                                        sheet_path=location.sheet_path,
                                        center_x=location.center_x,
                                        center_y=location.center_y,
                                        number=task_name,
                                        save_dir=save_dir,
                                        task_positions=[{
                                            'pos_x': location.center_x,
                                            'pos_y': location.center_y,
                                            'task_type': 'BC_TASK',
                                            'is_main': True
                                        }],
                                        filename_prefix=f"no_{task_name}_{rejected_count}"
                                    )
                                    print(f"Saved rejected BC match image: no_{task_name}_{rejected_count}.jpg")
                                except Exception as e:
                                    print(f"Error saving rejected match image: {str(e)}")
                            
                            # Mark this match as shown
                            matches_shown.add(current_match_index)
                            
                            current_match_index += 1
                            
                            # If we've reached the end, loop back to the beginning
                            if current_match_index >= len(locations):
                                print(f"Reached end of matches for {task_name}, looping back to first match")
                                current_match_index = 0
                                
                                # If we've shown all matches at least once, require a decision
                                if len(matches_shown) >= len(locations):
                                    print(f"All {total_matches} matches have been reviewed for {task_name}")
                                    print("You must either accept a match or skip this task.")
                    elif result == True:
                        location_found = True
                        
                if location_found:
                    print(f"Successfully processed BC task {task_name} (Update in progress)")
                else:
                    print(f"No suitable location found for BC task {task_name}")
                    
                remaining_tasks -= 1
                current_task_index += 1
                
            # Cleanup
            stop_event.set()
            search_thread.join(timeout=5)
            update_thread.join(timeout=5)
            
            # Wait for final updates
            print("\nWaiting for remaining BC task updates to complete...")
            try:
                wait_start = time.time()
                timeout = 60
                
                prev_size = update_queue.qsize()
                while not update_queue.empty():
                    if time.time() - wait_start > timeout:
                        remaining = update_queue.qsize()
                        print(f"Timed out waiting for {remaining} BC task updates to complete.")
                        break
                    
                    current_size = update_queue.qsize()
                    if current_size != prev_size:
                        print(f"Processing BC updates: {current_size} remaining...")
                        prev_size = current_size
                    
                    time.sleep(1.0)
                
                if update_queue.empty():
                    print("All BC task updates completed successfully.")
                else:
                    print(f"Exiting with {update_queue.qsize()} BC task updates still pending.")
            except Exception as e:
                print(f"Error while waiting for BC updates to complete: {str(e)}")
            
        print("\nBC task location processing completed")

    def _process_bc_task_location_with_async_update(
        self,
        project_id: str,
        task: Dict,
        sheet: Dict,
        center_x: float,
        center_y: float,
        task_name: str,
        user_id: int,
        sheet_path: str,
        save_dir: str = None,
        rejected_count: int = 0,
        update_queue: queue.Queue = None,
        match_number: int = 1,
        total_matches: int = 1
    ) -> Union[bool, Tuple[str, bool]]:
        """Process a single BC task location with user interaction and async updates.
        
        BC mode differences:
        - Only one task position (no related tasks)
        - No distance adjustment controls
        - Simplified preview with single marker
        """
        while True:  # Loop for position adjustment only
            # Calculate position for single BC task
            task_position = {
                'pos_x': center_x,
                'pos_y': center_y,
                'task_type': 'BC_TASK',
                'is_main': True
            }
            
            # Show preview with single task position (no distance controls)
            print(f"\n=========================================================")
            print(f"Found potential BC match on sheet {sheet['name']}")
            print(f"Task: {task_name} (Match {match_number} of {total_matches})")
            print(f"Opening a BC preview window for user interaction...")
            print(f"Creating BC mode preview with distance controls DISABLED")
            print(f"=========================================================")
            
            # Create and show preview window (with no distance adjustment)
            # Create match info string for display including sheet name and page number
            sheet_name = sheet.get('name', 'Unknown Sheet')
            page_number = sheet.get('page_number', 'Unknown')
            match_info = f"{task_name} (Match {match_number} of {total_matches}) - Sheet: {sheet_name} - Page: {page_number}"
            
            try:
                preview_window = PreviewWindow(
                    image_url=f"file://{sheet_path}",
                    locations=[task_position],
                    current_distance=0,  # No distance adjustment in BC mode
                    task_name=match_info,  # Show the task name with match info
                    enable_distance_controls=False  # EXPLICITLY disable distance controls for BC mode
                )
                
                # Show the window and wait for user input
                print("Waiting for user to interact with the BC preview window...")
                choice, _ = preview_window.show()  # Ignore distance since it's not used
                print(f"User selected: {choice} in BC mode (distance controls disabled)")
            except Exception as e:
                print(f"Error displaying BC preview window: {str(e)}")
                import traceback
                traceback.print_exc()
                return 'skipped', False
            
            # Handle directional movement
            if choice in ['up', 'down', 'left', 'right']:
                # Adjust center position by 10 pixels
                old_x, old_y = center_x, center_y
                if choice == 'up':
                    center_y -= 10
                elif choice == 'down':
                    center_y += 10
                elif choice == 'left':
                    center_x -= 10
                elif choice == 'right':
                    center_x += 10
                print(f"Adjusted BC position: ({old_x}, {old_y}) -> ({center_x}, {center_y})")
                continue  # Show preview again with new position
            
            # Note: BC mode does not support spacing adjustments (z/x keys are disabled)
            
            if choice == 'y':
                try:
                    if 'floorplan_id' not in sheet:
                        print("Error: Sheet is missing floorplan_id. Skipping this result.")
                        return 'skipped', False
                    
                    # Queue the task update for background processing
                    if update_queue:
                        update_task = (
                            task_name,             # Task name
                            task['id'],            # Task ID
                            sheet,                 # Sheet
                            center_x,              # X coordinate
                            center_y,              # Y coordinate
                            user_id,               # User ID
                            sheet_path,            # Sheet path
                            task_position,         # Task position for image saving
                            save_dir               # Save directory
                        )
                        
                        # Add to the update queue
                        update_queue.put(update_task)
                        print("BC task update queued - continuing to next task")
                        
                        # Return immediately to continue processing
                        return 'accepted', False
                    else:
                        # Fallback to synchronous update if no queue provided
                        print("Warning: No update queue available, performing synchronous update")
                        updated_task = self.update_task_location(
                            project_id=project_id,
                            task_id=task['id'],
                            floorplan_id=sheet['floorplan_id'],
                            pos_x=center_x,
                            pos_y=center_y,
                            last_editor_user_id=user_id
                        )
                        
                        if not updated_task:
                            print("Failed to update BC task location. Canceling sequence.")
                            return 'skipped', False
                            
                        # Save image for successful match
                        if save_dir:
                            try:
                                self._save_preview_image(
                                    sheet_path=sheet_path,
                                    center_x=center_x,
                                    center_y=center_y,
                                    number=task_name,
                                    save_dir=save_dir,
                                    task_positions=[task_position],
                                    filename_prefix=f"yes_{task_name}"
                                )
                                print(f"Preview image saved for accepted BC match: yes_{task_name}.jpg")
                            except Exception as e:
                                print(f"Error saving preview image: {str(e)}")
                        
                        return 'accepted', False
                except ValueError as e:
                    print(f"Error updating BC task location: {str(e)}")
                    print("Canceling sequence.")
                    return 'skipped', False
            elif choice == 's':
                # Skip this task entirely (no more matches will be shown)
                if save_dir:
                    try:
                        # Save preview image with no_ prefix and sequence number
                        rejected_count += 1
                        self._save_preview_image(
                            sheet_path=sheet_path,
                            center_x=center_x,
                            center_y=center_y,
                            number=task_name,
                            save_dir=save_dir,
                            task_positions=[task_position],
                            filename_prefix=f"no_{task_name}_{rejected_count}"
                        )
                        print(f"Preview image saved for skipped BC match: no_{task_name}_{rejected_count}.jpg")
                    except Exception as e:
                        print(f"Error saving rejected match image: {str(e)}")
                return 'skipped', True  # Skip the entire task
            elif choice == 'n':
                # Go to next match (this match is rejected)
                print(f"Moving to next match for task {task_name}")
                return 'next', True  # Move to next match, this one was rejected
            elif choice in ['z', 'x']:
                # These should be disabled in BC mode but handle them just in case
                print(f"Warning: Distance adjustment key '{choice}' pressed in BC mode (should be disabled)")
                continue
            else:
                print(f"User choice '{choice}' not recognized or window was closed. Skipping BC task.")
                return 'skipped', False
