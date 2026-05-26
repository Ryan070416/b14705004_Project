import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, colorchooser
from PIL import Image, ImageTk
import json
import os
import shutil
import uuid

# ==========================================
# 1. 資料模型 (Class 定義)
# ==========================================
class Question:
    def __init__(self, q_id, q_name, subject, image_path, note_content, difficulty):
        self.id = q_id                   
        self.name = q_name               
        self.subject = subject  
        self.image_path = image_path     
        self.note_content = note_content 
        self.difficulty = int(difficulty)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "subject": self.subject,
            "image_path": self.image_path,
            "note_content": self.note_content,
            "difficulty": self.difficulty
        }

    @classmethod
    def from_dict(cls, data):
        note_data = data.get('note_content', [])
        if isinstance(note_data, str):
            note_data = [{"type": "text", "value": note_data}]

        return cls(
            data['id'], 
            data.get('name', f"錯題 {data['id'][:6]}"), 
            data['subject'], 
            data['image_path'], 
            note_data, 
            data['difficulty']
        )

# ==========================================
# 2. 應用程式主體 (Tkinter GUI)
# ==========================================
class DigitalErrorNotebookApp:
    def __init__(self, root):
        self.root = root
        self.root.title("數位錯題本 1.0 (Finder 終極整合版)")
        self.root.geometry("1100x750") 
        
        self.data_file = "questions_data.json"
        self.image_dir = "saved_images"
        if not os.path.exists(self.image_dir):
            os.makedirs(self.image_dir) 

        self.subjects = []  
        self.questions = []
        
        self._auto_save_job = None  
        self.dragged_items = None # 【新增】：支援多選拖曳
        self.drag_window = None   # 【新增】：幽靈拖曳視窗
        
        self.load_data() 
        self.setup_ui()  
        self.build_tree()

    def setup_ui(self):
        # -- 頂部工具列 --
        top_frame = tk.Frame(self.root, pady=10)
        top_frame.pack(fill=tk.X)

        tk.Button(top_frame, text="＋ 新增資料夾", command=self.add_new_folder, bg="lightgreen").pack(side=tk.LEFT, padx=(10, 5))
        tk.Button(top_frame, text="＋ 新增錯題", command=self.open_add_question_window, bg="lightblue").pack(side=tk.LEFT, padx=5)

        tk.Button(top_frame, text="－ 刪除選定項目", command=self.delete_selected, bg="#ff9999").pack(side=tk.RIGHT, padx=20)

        # -- 雙欄式主佈局 --
        self.main_paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashrelief=tk.RAISED, sashwidth=6)
        self.main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 【左欄：Finder 樹狀目錄】
        left_frame = tk.Frame(self.main_paned, bg="#f0f0f0")
        
        sort_frame = tk.Frame(left_frame, bg="#f0f0f0")
        sort_frame.pack(fill=tk.X, pady=5)
        tk.Button(sort_frame, text="錯題難度 ▲", command=lambda: self.sort_questions(False)).pack(side=tk.LEFT, padx=2, expand=True, fill=tk.X)
        tk.Button(sort_frame, text="錯題難度 ▼", command=lambda: self.sort_questions(True)).pack(side=tk.LEFT, padx=2, expand=True, fill=tk.X)

        # 【修改】：selectmode 改為 extended 支援多重選取 (Cmd/Shift + Click)
        self.tree = ttk.Treeview(left_frame, selectmode="extended", show="tree")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.tree.bind('<<TreeviewSelect>>', self.on_tree_select)
        self.tree.bind("<ButtonPress-1>", self.on_drag_start)
        self.tree.bind("<B1-Motion>", self.on_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self.on_drag_release)

        self.main_paned.add(left_frame, minsize=250, width=300)

        # 【右欄：題目詳細內容區】
        right_frame = tk.Frame(self.main_paned)
        self.right_paned = tk.PanedWindow(right_frame, orient=tk.VERTICAL, sashrelief=tk.RAISED, sashwidth=8)
        self.right_paned.pack(fill=tk.BOTH, expand=True)

        self.img_frame = tk.Frame(self.right_paned)
        self.img_label = tk.Label(self.img_frame, text="請選擇左側題目以顯示圖片\n(點擊圖片可放大檢視)", bg="lightgray", cursor="hand2")
        self.img_label.pack(fill=tk.BOTH, expand=True)
        self.img_label.bind("<Button-1>", self.show_full_image)
        self.right_paned.add(self.img_frame, minsize=150)

        self.note_frame = tk.Frame(self.right_paned)
        top_note_frame = tk.Frame(self.note_frame)
        top_note_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.note_title_label = tk.Label(top_note_frame, text="我的解答筆記 (自動儲存)：", font=("Arial", 12, "bold"))
        self.note_title_label.pack(side=tk.LEFT)
        self.note_status_label = tk.Label(top_note_frame, text="", fg="gray", font=("Arial", 10))
        self.note_status_label.pack(side=tk.RIGHT, padx=10)
        
        self.note_toolbar = tk.Frame(self.note_frame)
        self.note_toolbar.pack(fill=tk.X, pady=2)
        self.note_text = tk.Text(self.note_frame, height=8, font=("Arial", 14), wrap=tk.WORD)
        self.note_text.pack(fill=tk.BOTH, expand=True, pady=2)
        
        self.main_note_images = {}
        self.main_toolbar_widgets = self.setup_rich_text_tools(
            self.note_toolbar, self.note_text, self.main_note_images, on_change_callback=self.schedule_auto_save
        )
        self.right_paned.add(self.note_frame, minsize=200)
        self.main_paned.add(right_frame, minsize=400)
        
        self.set_note_state(tk.DISABLED)

    # ==========================================
    # Finder 樹狀結構建構與「視覺化拖曳」邏輯
    # ==========================================
    def build_tree(self):
        expanded_nodes = [item for item in self.tree.get_children("") if self.tree.item(item, "open")]
        def get_all_expanded(parent):
            for child in self.tree.get_children(parent):
                if self.tree.item(child, "open"): expanded_nodes.append(child)
                get_all_expanded(child)
        get_all_expanded("")
        
        selected_items = self.tree.selection()

        for item in self.tree.get_children():
            self.tree.delete(item)
            
        self.tree.insert("", "end", "root", text="🏠 根目錄 (最外層)", open=True)

        all_paths = set(self.subjects)
        for s in list(all_paths):
            parts = s.split('/')
            for i in range(1, len(parts)):
                all_paths.add('/'.join(parts[:i]))
        self.subjects = sorted(list(all_paths))

        for path in self.subjects:
            if not path: continue
            parts = path.split('/')
            parent = "root" if len(parts) == 1 else '/'.join(parts[:-1])
            folder_name = parts[-1]
            self.tree.insert(parent, "end", path, text=f"📁 {folder_name}")

        for q in self.questions:
            parent = q.subject if q.subject else "root"
            if parent != "root" and not self.tree.exists(parent):
                parent = "root"
                q.subject = ""
            
            node_id = f"q_{q.id}"
            self.tree.insert(parent, "end", node_id, text=f"📄 [難度: {q.difficulty}] {q.name}")

        for node in expanded_nodes:
            if self.tree.exists(node): self.tree.item(node, open=True)
            
        for sel in selected_items:
            if self.tree.exists(sel):
                self.tree.selection_add(sel)
        if selected_items and self.tree.exists(selected_items[0]):
            self.tree.see(selected_items[0])

    # -- 新版：多選與視覺化拖曳核心 --
    def on_drag_start(self, event):
        self.dragged_items = None
        if self.drag_window:
            self.drag_window.destroy()
            self.drag_window = None
            
        item = self.tree.identify_row(event.y)
        if not item or item == "root": return
        
        # 紀錄起始座標，用來判定是否真的開始拖拉 (防手震)
        self._drag_start_x = event.x
        self._drag_start_y = event.y

    def on_drag_motion(self, event):
        if not hasattr(self, '_drag_start_x'): return
        
        # 如果還沒生成幽靈視窗，代表剛開始拖曳
        if not self.dragged_items:
            # 防手震：滑鼠移動超過 5 像素才判定為拖曳
            if abs(event.x - self._drag_start_x) < 5 and abs(event.y - self._drag_start_y) < 5:
                return
                
            sel = self.tree.selection()
            item_under_cursor = self.tree.identify_row(self._drag_start_y)
            
            # 判斷使用者拖曳的是「已經多選的群組」還是「單一未選取項目」
            if item_under_cursor in sel:
                self.dragged_items = [i for i in sel if i != "root"]
            else:
                self.dragged_items = [item_under_cursor] if item_under_cursor and item_under_cursor != "root" else []
                
            if not self.dragged_items: return
            
            # 【視覺化回饋】：建立透明跟隨視窗
            self.drag_window = tk.Toplevel(self.root)
            self.drag_window.overrideredirect(True)
            self.drag_window.attributes("-alpha", 0.85) # 85% 透明度
            
            if len(self.dragged_items) > 1:
                lbl_text = f"📦 正在移動 {len(self.dragged_items)} 個項目..."
            else:
                lbl_text = self.tree.item(self.dragged_items[0], "text")
                
            tk.Label(self.drag_window, text=lbl_text, bg="#d0e2ff", font=("Arial", 12), relief=tk.SOLID, bd=1, padx=8, pady=4).pack()

        # 讓幽靈視窗跟隨滑鼠
        if self.drag_window:
            self.drag_window.geometry(f"+{event.x_root + 15}+{event.y_root + 15}")
            
        # 標示即將放入的目標資料夾
        target = self.tree.identify_row(event.y)
        if target:
            self.tree.selection_set(target) 

    def on_drag_release(self, event):
        # 銷毀幽靈視窗
        if self.drag_window:
            self.drag_window.destroy()
            self.drag_window = None
            
        if not getattr(self, 'dragged_items', None): return
        
        target_item = self.tree.identify_row(event.y)
        dragged = self.dragged_items
        self.dragged_items = None 
        
        if not target_item or target_item in dragged: 
            self.build_tree() 
            return

        # 解析目標路徑
        if target_item == "root":
            target_folder = ""
        elif target_item.startswith("q_"):
            q_id = target_item[2:]
            q = next((q for q in self.questions if q.id == q_id), None)
            target_folder = q.subject if q else ""
        else:
            target_folder = target_item 

        moved_count = 0
        
        # 批次處理所有被拖曳的物件
        for item in dragged:
            if item.startswith("q_"):
                # 移動錯題
                q_id = item[2:]
                q = next((q for q in self.questions if q.id == q_id), None)
                if q and q.subject != target_folder:
                    q.subject = target_folder
                    moved_count += 1
            else:
                # 移動資料夾
                if target_folder == item or target_folder.startswith(item + "/"):
                    continue # 防呆：不能把資料夾塞進自己的肚子裡
                    
                old_path = item
                folder_name = old_path.split("/")[-1]
                new_path = folder_name if target_folder == "" else f"{target_folder}/{folder_name}"
                
                if new_path in self.subjects: continue
                
                new_subjects = set()
                for s in self.subjects:
                    if s == old_path: new_subjects.add(new_path)
                    elif s.startswith(old_path + "/"): new_subjects.add(s.replace(old_path, new_path, 1))
                    else: new_subjects.add(s)
                self.subjects = sorted(list(new_subjects))
                
                for q in self.questions:
                    if q.subject == old_path: q.subject = new_path
                    elif q.subject.startswith(old_path + "/"): q.subject = q.subject.replace(old_path, new_path, 1)
                moved_count += 1

        if moved_count > 0:
            self.save_data()
            
        self.build_tree()
        
        # 恢復選取狀態
        for item in dragged:
            new_selection = item if item.startswith("q_") else new_path if not item.startswith("q_") else item
            if self.tree.exists(new_selection):
                self.tree.selection_add(new_selection)
                self.tree.see(new_selection)
        self.on_tree_select()

    def on_tree_select(self, event=None):
        # 拖曳時產生的選取變更不要觸發右側刷新，避免畫面閃爍
        if getattr(self, 'dragged_items', None): return
        
        selected = self.tree.selection()
        # 若沒有選取，或是多重選取，則清空右側編輯器（一次只能編輯一題）
        if not selected or len(selected) > 1: 
            self.clear_right_pane()
            if len(selected) > 1:
                self.note_title_label.config(fg="gray", text=f"已選取 {len(selected)} 個項目 (可拖曳或批次刪除)")
            return
            
        item = selected[0]
        if item.startswith("q_"):
            q_id = item[2:]
            q = next((q for q in self.questions if q.id == q_id), None)
            if not q: return

            try:
                img = Image.open(q.image_path)
                self.right_paned.update_idletasks()
                img.thumbnail((700, 400)) 
                photo = ImageTk.PhotoImage(img)
                self.img_label.config(image=photo, text="")
                self.img_label.image = photo 
            except Exception:
                self.img_label.config(image='', text="圖片載入失敗或遺失")

            self.set_note_state(tk.NORMAL)
            self.deserialize_note(self.note_text, q.note_content, self.main_note_images)
        else:
            self.clear_right_pane()

    def clear_right_pane(self):
        self.img_label.config(image='', text="請選擇目錄中的錯題以顯示圖片\n(點擊圖片可放大檢視)")
        self.note_text.config(state=tk.NORMAL)
        self.note_text.delete(1.0, tk.END)
        self.set_note_state(tk.DISABLED)
        self.note_status_label.config(text="")

    def sort_questions(self, reverse_order):
        self.questions.sort(key=lambda q: q.difficulty, reverse=reverse_order)
        self.build_tree()

    # ==========================================
    # 批次刪除與新增邏輯
    # ==========================================
    def add_new_folder(self):
        selected = self.tree.selection()
        if not selected or selected[0] == "root":
            parent_path = "root"
        elif selected[0].startswith("q_"):
            q_id = selected[0][2:]
            q = next((q for q in self.questions if q.id == q_id), None)
            parent_path = q.subject if q and q.subject else "root"
        else:
            parent_path = selected[0]
        
        new_folder_name = simpledialog.askstring("新增資料夾", "請輸入新資料夾名稱 (不含斜線)：", parent=self.root)
        if new_folder_name:
            new_folder_name = new_folder_name.replace("/", "").strip()
            if not new_folder_name: return
            new_full_path = new_folder_name if parent_path == "root" else f"{parent_path}/{new_folder_name}"
            
            if new_full_path in self.subjects:
                messagebox.showwarning("警告", "此資料夾已存在！", parent=self.root)
                return
                
            self.subjects.append(new_full_path)
            self.save_data()
            self.build_tree()
            self.tree.selection_set(new_full_path)
            self.tree.see(new_full_path)

    def delete_selected(self):
        """【升級】：支援批次多選刪除！"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("警告", "請先選擇你要刪除的項目！", parent=self.root)
            return
            
        if "root" in selected:
            selected = [s for s in selected if s != "root"]
            if not selected:
                messagebox.showwarning("警告", "無法刪除根目錄！", parent=self.root)
                return

        confirm = messagebox.askyesno("確認刪除", f"確定要刪除選定的 {len(selected)} 個項目嗎？\n\n提示：刪除資料夾時，內部的「錯題」將自動散落遣返到最外層 (根目錄)。", parent=self.root)
        if not confirm: return

        # 區分要刪除的題目與資料夾
        q_items = [i for i in selected if i.startswith("q_")]
        f_items = [i for i in selected if not i.startswith("q_")]

        # 1. 批次刪除錯題
        for item in q_items:
            q_id = item[2:]
            q_to_delete = next((q for q in self.questions if q.id == q_id), None)
            if q_to_delete:
                self.questions.remove(q_to_delete)
                if os.path.exists(q_to_delete.image_path):
                    try: os.remove(q_to_delete.image_path)
                    except Exception: pass
                    
                for note_item in q_to_delete.note_content:
                    if note_item["type"] == "image" and os.path.exists(note_item["value"]):
                        try: os.remove(note_item["value"])
                        except Exception: pass

        # 2. 批次刪除資料夾
        for path_to_delete in f_items:
            for q in self.questions:
                if q.subject == path_to_delete:
                    q.subject = "" 
                elif q.subject.startswith(path_to_delete + "/"):
                    q.subject = q.subject[len(path_to_delete + "/"):]

            new_subjects = set()
            for s in self.subjects:
                if s == path_to_delete: continue 
                elif s.startswith(path_to_delete + "/"):
                    new_subjects.add(s[len(path_to_delete + "/"):])
                else:
                    new_subjects.add(s)
            self.subjects = sorted(list(new_subjects))

        self.save_data()
        self.build_tree()
        self.clear_right_pane()
        messagebox.showinfo("成功", f"成功移除了 {len(selected)} 個項目！", parent=self.root)

    # ==========================================
    # 狀態管理與自動儲存 (Auto-Save)
    # ==========================================
    def set_note_state(self, state):
        bg_color = "#f0f0f0" if state == tk.DISABLED else "white"
        self.note_text.config(state=state, bg=bg_color)
        for widget in self.main_toolbar_widgets:
            widget.config(state=state)
            
        if state == tk.DISABLED:
            # 防呆文字會在 on_tree_select 中被更詳細的多選文字蓋過
            self.note_title_label.config(fg="gray", text="請先選擇目錄中的「單一錯題」才能撰寫筆記")
        else:
            self.note_title_label.config(fg="black", text="我的解答筆記 (自動儲存)：")

    def schedule_auto_save(self, event=None):
        selected = self.tree.selection()
        if not selected or len(selected) > 1 or not selected[0].startswith("q_"): return
        self.note_status_label.config(text="正在儲存...", fg="blue")
        if self._auto_save_job:
            self.root.after_cancel(self._auto_save_job)
        self._auto_save_job = self.root.after(500, self.perform_auto_save)

    def perform_auto_save(self):
        selected = self.tree.selection()
        if not selected: return
        item = selected[0]
        if not item.startswith("q_"): return
        
        q_id = item[2:]
        q = next((q for q in self.questions if q.id == q_id), None)
        if q:
            q.note_content = self.serialize_note(self.note_text, self.main_note_images)
            self.save_data()
            self.note_status_label.config(text="已儲存 ✓", fg="green")
            self.root.after(3000, lambda: self.note_status_label.config(text=""))

    # ==========================================
    # Rich Text (富文本編輯器) 核心工具
    # ==========================================
    def setup_rich_text_tools(self, parent_toolbar, text_widget, image_dict, on_change_callback=None):
        widgets = []
        def notify_change(event=None):
            if on_change_callback: on_change_callback()

        text_widget.bind("<KeyRelease>", notify_change)

        size_var = tk.StringVar(value="14")
        size_cb = ttk.Combobox(parent_toolbar, textvariable=size_var, values=[str(i) for i in range(10, 101, 2)], width=4)
        size_cb.pack(side=tk.LEFT, padx=(2, 10))
        widgets.append(size_cb)
        
        def apply_size(event=None):
            size_val = size_var.get()
            if size_val.isdigit():
                self.apply_dynamic_tag(text_widget, f"size_{size_val}", font=("Arial", int(size_val)))
                notify_change()
        
        size_cb.bind("<<ComboboxSelected>>", apply_size)
        size_cb.bind("<Return>", apply_size) 

        def apply_bold():
            self.apply_dynamic_tag(text_widget, "bold", font=("Arial", int(size_var.get()), "bold"))
            notify_change()
            
        btn_bold = tk.Button(parent_toolbar, text="B", font=("Arial", 11, "bold"), command=apply_bold)
        btn_bold.pack(side=tk.LEFT, padx=2)
        widgets.append(btn_bold)

        color_btn = tk.Button(parent_toolbar, text="A (顏色) ▼", font=("Arial", 11, "bold"))
        color_btn.pack(side=tk.LEFT, padx=10)
        color_btn.config(command=lambda: self.open_color_picker(color_btn, text_widget, notify_change))
        widgets.append(color_btn)

        def trigger_insert_img():
            text_widget.after(50, lambda: self._perform_insert_image(text_widget, image_dict, notify_change))
            
        btn_img = tk.Button(parent_toolbar, text="🖼️ 插入圖片", command=trigger_insert_img)
        btn_img.pack(side=tk.LEFT, padx=10)
        widgets.append(btn_img)

        text_widget.tag_configure("bold", font=("Arial", 14, "bold"))
        return widgets

    def apply_dynamic_tag(self, text_widget, tag_name, **kwargs):
        try:
            if text_widget.tag_ranges(tk.SEL): 
                first = tk.SEL_FIRST
                last = tk.SEL_LAST
                text_widget.tag_add(tag_name, first, last)
                text_widget.tag_configure(tag_name, **kwargs)
        except tk.TclError:
            pass 

    def open_color_picker(self, button_widget, text_widget, notify_change):
        picker = tk.Toplevel(self.root)
        picker.overrideredirect(True) 
        x = button_widget.winfo_rootx()
        y = button_widget.winfo_rooty() + button_widget.winfo_height()
        picker.geometry(f"+{x}+{y}")
        picker.configure(bg="#e0e0e0", bd=1, relief=tk.SOLID)

        color_matrix = [
            ["#000000", "#434343", "#666666", "#999999", "#cccccc", "#efefef", "#ffffff"],
            ["#980000", "#ff0000", "#ff9900", "#ffff00", "#00ff00", "#00ffff", "#4a86e8", "#0000ff", "#9900ff", "#ff00ff"],
            ["#e6b8af", "#f4cccc", "#fce5cd", "#fff2cc", "#d9ead3", "#d0e0e3", "#c9daf8", "#cfe2f3", "#d9d2e9", "#ead1dc"],
            ["#cc4125", "#e06666", "#f6b26b", "#ffd966", "#93c47d", "#76a5af", "#6d9eeb", "#6fa8dc", "#8e7cc3", "#c27ba0"],
            ["#a61c00", "#cc0000", "#e69138", "#f1c232", "#6aa84f", "#45818e", "#3c78d8", "#3d85c6", "#674ea7", "#a64d79"],
            ["#5b0f00", "#660000", "#783f04", "#7f6000", "#274e13", "#0c343d", "#1c4587", "#073763", "#20124d", "#4c1130"]
        ]
        frame = tk.Frame(picker, bg="white", padx=5, pady=5)
        frame.pack()

        def restore_focus(): text_widget.focus_force()

        def set_color(c):
            self.apply_dynamic_tag(text_widget, f"color_{c}", foreground=c)
            notify_change() 
            picker.destroy()
            text_widget.after(50, restore_focus)

        def open_os_colorchooser():
            color = colorchooser.askcolor(parent=picker, title="自訂顏色")[1]
            if color: set_color(color)
            else:
                picker.destroy()
                text_widget.after(50, restore_focus)

        for r_idx, row in enumerate(color_matrix):
            for c_idx, c in enumerate(row):
                lbl = tk.Label(frame, bg=c, width=2, height=1, relief=tk.RIDGE, cursor="hand2")
                lbl.bind("<Button-1>", lambda e, col=c: set_color(col))
                lbl.grid(row=r_idx, column=c_idx, padx=1, pady=1)

        custom_btn = tk.Button(frame, text="自訂更多顏色...", command=open_os_colorchooser, relief=tk.FLAT, bg="#f0f0f0")
        custom_btn.grid(row=len(color_matrix), column=0, columnspan=10, sticky="we", pady=(5,0))

        def on_focus_out(event):
            if event.widget == picker:
                if picker.winfo_exists():
                    picker.destroy()
                    text_widget.after(50, restore_focus)

        picker.bind("<FocusOut>", on_focus_out)
        picker.focus_set()

    def _perform_insert_image(self, text_widget, image_dict, notify_change):
        parent_win = text_widget.winfo_toplevel()
        filepath = filedialog.askopenfilename(
            parent=parent_win, title="選擇要插入筆記的圖片",
            filetypes=[
                ("PNG Image", "*.png"), ("JPEG Image", "*.jpg"),
                ("JPEG Image", "*.jpeg"), ("BMP Image", "*.bmp"), ("All Files", "*.*")
            ]
        )
        if filepath:
            ext = os.path.splitext(filepath)[1]
            new_name = f"note_{uuid.uuid4().hex}{ext}"
            new_path = os.path.join(self.image_dir, new_name)
            shutil.copy(filepath, new_path)
            img = Image.open(new_path)
            img.thumbnail((400, 300))
            photo = ImageTk.PhotoImage(img)
            img_id = text_widget.image_create(tk.INSERT, image=photo)
            image_dict[img_id] = (new_path, photo)
            notify_change() 
            parent_win.lift()

    def serialize_note(self, text_widget, image_dict):
        content = []
        dump = text_widget.dump("1.0", "end-1c")
        for item_type, value, index in dump:
            if item_type == "tagon" and value != "sel": content.append({"type": "tagon", "value": value})
            elif item_type == "tagoff" and value != "sel": content.append({"type": "tagoff", "value": value})
            elif item_type == "text": content.append({"type": "text", "value": value})
            elif item_type == "image":
                if value in image_dict: content.append({"type": "image", "value": image_dict[value][0]})
        return content

    def deserialize_note(self, text_widget, content_list, image_dict):
        text_widget.config(state=tk.NORMAL)
        text_widget.delete("1.0", tk.END)
        image_dict.clear()
        current_tags = set()
        for item in content_list:
            if item["type"] == "text":
                text_widget.insert(tk.END, item["value"], tuple(current_tags))
            elif item["type"] == "tagon":
                tag_name = item["value"]
                current_tags.add(tag_name)
                if tag_name.startswith("color_"): text_widget.tag_configure(tag_name, foreground=tag_name.split("_")[1])
                elif tag_name.startswith("size_"): text_widget.tag_configure(tag_name, font=("Arial", int(tag_name.split("_")[1])))
            elif item["type"] == "tagoff": current_tags.discard(item["value"])
            elif item["type"] == "image":
                path = item["value"]
                if os.path.exists(path):
                    img = Image.open(path)
                    img.thumbnail((400, 300))
                    photo = ImageTk.PhotoImage(img)
                    img_id = text_widget.image_create(tk.END, image=photo)
                    image_dict[img_id] = (path, photo)

    def load_data(self):
        if os.path.exists(self.data_file):
            with open(self.data_file, 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.questions = [Question.from_dict(q) for q in data]
                        self.subjects = list(set([q.subject for q in self.questions]))
                    else:
                        self.subjects = data.get("subjects", [])
                        self.questions = [Question.from_dict(q) for q in data.get("questions", [])]
                except:
                    self.questions = []
                    self.subjects = []

    def save_data(self):
        data = {"subjects": self.subjects, "questions": [q.to_dict() for q in self.questions]}
        with open(self.data_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def show_full_image(self, event):
        selected = self.tree.selection()
        if not selected or not selected[0].startswith("q_"): return
        
        q_id = selected[0][2:]
        q = next((q for q in self.questions if q.id == q_id), None)
        if not q or not os.path.exists(q.image_path):
            messagebox.showerror("錯誤", "找不到實體圖片檔案！", parent=self.root)
            return

        img_win = tk.Toplevel(self.root)
        img_win.title(f"完整檢視 - {q.name}")
        img_win.configure(bg="black")
        win_w, win_h = int(img_win.winfo_screenwidth() * 0.9), int(img_win.winfo_screenheight() * 0.9)
        img_win.geometry(f"{win_w}x{win_h}")
        
        try:
            orig_img = Image.open(q.image_path)
            orig_img.thumbnail((win_w - 40, win_h - 40))
            full_photo = ImageTk.PhotoImage(orig_img)
            label = tk.Label(img_win, image=full_photo, bg="black")
            label.pack(fill=tk.BOTH, expand=True)
            label.image = full_photo 
        except Exception as e:
            messagebox.showerror("錯誤", f"無法顯示圖片：{e}", parent=img_win)
            img_win.destroy()

    # ==========================================
    # 新增題目的獨立視窗 
    # ==========================================
    def open_add_question_window(self):
        selected = self.tree.selection()
        if not selected:
            target_subject = "root"
        else:
            item = selected[0]
            if item == "root": target_subject = "root"
            elif item.startswith("q_"):
                q = next((q for q in self.questions if q.id == item[2:]), None)
                target_subject = q.subject if q and q.subject else "root"
            else: target_subject = item
            
        display_target = "🏠 根目錄" if target_subject == "root" else f"📁 {target_subject}"

        add_win = tk.Toplevel(self.root)
        add_win.title("新增錯題")
        add_win.geometry("500x550")
        
        tk.Label(add_win, text=f"目標儲存位置：【{display_target}】", font=("Arial", 11, "bold"), fg="blue").pack(pady=5)
        
        tk.Label(add_win, text="自訂錯題名稱:").pack(pady=5)
        q_name_entry = tk.Entry(add_win, width=30)
        q_name_entry.pack(pady=5)

        tk.Label(add_win, text="題目圖片:").pack(pady=5)
        img_path_var = tk.StringVar()
        img_entry = tk.Entry(add_win, textvariable=img_path_var, state='readonly', width=30)
        img_entry.pack(side=tk.TOP, pady=5)
        
        def choose_image():
            filepath = filedialog.askopenfilename(
                parent=add_win, title="選擇題目圖片",
                filetypes=[("PNG Image", "*.png"), ("JPEG Image", "*.jpg"), ("JPEG Image", "*.jpeg"), ("BMP Image", "*.bmp"), ("All Files", "*.*")]
            )
            if filepath:
                img_path_var.set(filepath)
                add_win.lift()
                
        tk.Button(add_win, text="瀏覽圖片...", command=lambda: add_win.after(50, choose_image)).pack(pady=5)

        tk.Label(add_win, text="難度 (0~2^32):").pack(pady=5)
        diff_entry = tk.Entry(add_win)
        diff_entry.pack(pady=5)
        diff_entry.insert(0, "1")

        tk.Label(add_win, text="解答與思路 (支援圖文與樣式):").pack(pady=(5,0))
        
        ans_toolbar = tk.Frame(add_win)
        ans_toolbar.pack(fill=tk.X, padx=10)
        ans_text = tk.Text(add_win, height=6, width=40, font=("Arial", 14), wrap=tk.WORD)
        ans_text.pack(pady=2, padx=10, fill=tk.BOTH, expand=True)
        add_note_images = {}
        self.setup_rich_text_tools(ans_toolbar, ans_text, add_note_images)

        def save_new_question():
            q_name = q_name_entry.get().strip()
            orig_img = img_path_var.get()
            diff = diff_entry.get().strip()
            ans_content = self.serialize_note(ans_text, add_note_images)

            if not q_name or not orig_img or not diff.isdigit():
                messagebox.showerror("錯誤", "請確保「錯題名稱」、「圖片」已填寫，且難度為數字！", parent=add_win)
                return

            ext = os.path.splitext(orig_img)[1]
            new_img_name = f"{uuid.uuid4().hex}{ext}"
            new_img_path = os.path.join(self.image_dir, new_img_name)
            shutil.copy(orig_img, new_img_path)

            target_subject_to_save = "" if target_subject == "root" else target_subject
            new_q = Question(q_id=new_img_name, q_name=q_name, subject=target_subject_to_save, image_path=new_img_path, note_content=ans_content, difficulty=diff)
            self.questions.append(new_q)
            self.save_data()
            
            self.build_tree()
            self.tree.selection_set(f"q_{new_q.id}")
            self.tree.see(f"q_{new_q.id}")
            messagebox.showinfo("成功", "錯題已成功加入並儲存！", parent=add_win)
            add_win.destroy()

        tk.Button(add_win, text="儲存送出", command=save_new_question, bg="lightgreen").pack(pady=10)

if __name__ == "__main__":
    root = tk.Tk()
    app = DigitalErrorNotebookApp(root)
    root.mainloop()