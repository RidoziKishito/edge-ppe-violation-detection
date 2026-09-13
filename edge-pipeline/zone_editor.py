import argparse
import json
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

from PIL import Image, ImageTk


class ZoneEditor:
    def __init__(
        self,
        root,
        image_path,
        output_path,
        source_name=None,
        source_width=None,
        source_height=None,
    ):
        self.root = root
        self.root.title("Trinity Zone Editor (Polygon Mode)")
        self.output_path = Path(output_path)
        self.source_name = source_name
        self.source_width = source_width
        self.source_height = source_height

        self.original_image = Image.open(image_path)
        self.display_image, self.scale_factor = self._fit_image(self.original_image)
        self.tk_image = ImageTk.PhotoImage(self.display_image)

        self.current_mode = None
        self.points = {"danger": [], "warning": []}
        self.canvas_items = {"danger": [], "warning": []}
        self.colors = {"danger": "red", "warning": "gold"}

        self._build_ui()

    @staticmethod
    def _fit_image(image):
        max_width, max_height = 1000, 650
        scale = min(max_width / image.width, max_height / image.height, 1.0)
        if scale == 1.0:
            return image.copy(), scale
        size = (int(image.width * scale), int(image.height * scale))
        return image.resize(size, Image.Resampling.LANCZOS), scale

    def _build_ui(self):
        canvas_frame = tk.Frame(self.root)
        canvas_frame.pack(side=tk.LEFT, padx=10, pady=10)

        self.canvas = tk.Canvas(
            canvas_frame,
            width=self.display_image.width,
            height=self.display_image.height,
            cursor="cross",
        )
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)
        
        # Bind left click to add point, right click to close polygon
        self.canvas.bind("<Button-1>", self.on_left_click)
        self.canvas.bind("<Button-3>", self.on_right_click)

        controls = tk.Frame(self.root)
        controls.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)

        self.status = tk.Label(
            controls,
            text="Select a zone type below.",
            fg="navy",
            wraplength=180,
            font=("Arial", 10, "bold")
        )
        self.status.pack(pady=5)

        self.instruction = tk.Label(
            controls,
            text="Left-Click to add points.\nRight-Click to finish shape.",
            fg="gray",
            wraplength=180,
        )
        self.instruction.pack(pady=5)

        tk.Button(
            controls,
            text="Draw Danger Zone",
            bg="red",
            fg="white",
            width=16,
            command=lambda: self.set_mode("danger"),
        ).pack(pady=5)
        
        tk.Button(
            controls,
            text="Draw Warning Zone",
            bg="gold",
            fg="black",
            width=16,
            command=lambda: self.set_mode("warning"),
        ).pack(pady=5)
        
        tk.Button(
            controls,
            text="Save & Exit",
            bg="green",
            fg="white",
            width=16,
            command=self.save_and_exit,
            font=("Arial", 10, "bold")
        ).pack(side=tk.BOTTOM, pady=20)

    def set_mode(self, mode):
        self.current_mode = mode
        self.points[mode] = []
        
        # Clear existing drawing for this mode
        for item in self.canvas_items[mode]:
            self.canvas.delete(item)
        self.canvas_items[mode] = []
        
        self.status.config(
            text=f"Drawing {mode.upper()} zone.\nClick points on image.",
            fg=self.colors[mode],
        )

    def on_left_click(self, event):
        if not self.current_mode:
            messagebox.showwarning("Select zone", "Please select a zone type to draw first.")
            return

        mode = self.current_mode
        pts = self.points[mode]
        items = self.canvas_items[mode]
        
        pts.append((event.x, event.y))
        
        # Draw dot
        dot = self.canvas.create_oval(
            event.x - 3, event.y - 3, event.x + 3, event.y + 3,
            fill=self.colors[mode]
        )
        items.append(dot)
        
        # Draw line from previous point
        if len(pts) > 1:
            x1, y1 = pts[-2]
            line = self.canvas.create_line(
                x1, y1, event.x, event.y,
                fill=self.colors[mode], width=2
            )
            items.append(line)

    def on_right_click(self, event):
        if not self.current_mode:
            return
            
        mode = self.current_mode
        pts = self.points[mode]
        items = self.canvas_items[mode]
        
        if len(pts) < 3:
            messagebox.showwarning("Incomplete", "A polygon needs at least 3 points.")
            return
            
        # Draw line from last point to first point to close the polygon
        x_first, y_first = pts[0]
        x_last, y_last = pts[-1]
        line = self.canvas.create_line(
            x_last, y_last, x_first, y_first,
            fill=self.colors[mode], width=2
        )
        items.append(line)
        
        # Optionally, draw a semi-transparent polygon (Tkinter stipple is tricky, so we just use an outline polygon)
        flat_pts = [coord for pt in pts for coord in pt]
        poly = self.canvas.create_polygon(
            flat_pts, outline=self.colors[mode], fill='', width=3
        )
        items.append(poly)
        
        self.status.config(text=f"{mode.title()} zone finished.", fg="green")
        self.current_mode = None

    def _zone_from_bounds(self, mode, zone_id, name, zone_type):
        pts = self.points[mode]
        if len(pts) < 3:
            return None
            
        # Scale points back to original image resolution
        scaled_pts = [
            [int(x / self.scale_factor), int(y / self.scale_factor)]
            for (x, y) in pts
        ]
        
        return {
            "id": zone_id,
            "name": name,
            "type": zone_type,
            "polygon": scaled_pts,
        }

    def save_and_exit(self):
        new_zones = [
            zone
            for zone in (
                self._zone_from_bounds("danger", "Z01", "Danger Zone", "danger_zone"),
                self._zone_from_bounds("warning", "Z02", "Warning Zone", "warning_zone"),
            )
            if zone
        ]
        if not new_zones:
            messagebox.showinfo("No changes", "No zones were drawn.")
            self.root.destroy()
            return

        try:
            existing = json.loads(self.output_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            existing = {"zones": []}

        updated_types = {zone["type"] for zone in new_zones}
        zones = [
            zone
            for zone in existing.get("zones", [])
            if zone.get("type") not in updated_types
        ]
        zones.extend(new_zones)

        data = {
            "source": self.source_name,
            "width": self.source_width or self.original_image.width,
            "height": self.source_height or self.original_image.height,
            "zones": zones,
        }
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        messagebox.showinfo("Saved", f"Polygon zone profile saved to:\n{self.output_path}")
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="Create safety zones on a video frame.")
    parser.add_argument("image_path")
    parser.add_argument("--output", default="configs/zones.json")
    parser.add_argument("--source")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    args = parser.parse_args()

    root = tk.Tk()
    ZoneEditor(
        root,
        args.image_path,
        args.output,
        args.source,
        args.width,
        args.height,
    )
    root.mainloop()


if __name__ == "__main__":
    main()
