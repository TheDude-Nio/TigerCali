export interface User {
  id: number
  username: string
  school: string
  created_at?: string
}

export interface ArmorColor {
  key: string
  name: string
  sjtu: number
  hex: string
}

export interface ArmorTag {
  key: string
  name: string
  sjtu: number
  hotkey: string
}

export interface Meta {
  app_name: string
  invite_required: boolean
  armor_colors: ArmorColor[]
  armor_tags: ArmorTag[]
  export_formats: { key: string; name: string; line: string }[]
  point_orders: { key: string; name: string }[]
}

export interface ClassDef {
  name: string
  color?: string
  tag?: string
}

export type LabelConfig =
  | { mode: 'armor'; colors: string[]; tags: string[] }
  | { mode: 'custom'; names: string[] }

export type Role = 'owner' | 'manager' | 'annotator'
export type MemberStatus = 'labeling' | 'submitted' | 'approved' | 'rejected'
export type ImageStatus = 'todo' | 'done' | 'rework'

export interface TaskSettings {
  auto_sort: boolean
}

export interface Task {
  id: number
  name: string
  description: string
  task_type: string
  label_config: LabelConfig
  classes: ClassDef[]
  settings: TaskSettings
  status: 'active' | 'finished'
  created_at: string
  updated_at: string
  owner: User
  my_role: Role
  my_status: MemberStatus
  my_review_comment: string
  is_manager: boolean
}

export interface TaskSummary {
  id: number
  name: string
  status: 'active' | 'finished'
  created_at: string
  owner: User
  my_role: Role
  my_status: MemberStatus
  is_manager: boolean
  total: number
  done: number
  my_assigned: number
  my_done: number
  members: number
  class_count: number
}

export type Point = [number, number]

export interface Ann {
  cls: number
  pts: Point[]
}

export interface ImageItem {
  id: number
  filename: string
  status: ImageStatus
  ann_count: number
  flagged: boolean
}

export interface ImageDetail extends ImageItem {
  task_id: number
  width: number
  height: number
  annotations: Ann[]
  review_note: string
  version: number
  assignee_id: number | null
  updated_at: string | null
  updated_by: number | null
}

export interface Progress {
  assigned: number
  done: number
  todo: number
  rework: number
  ann_count: number
  flagged: number
  done_today: number
}

export interface MyProgress extends Progress {
  status: MemberStatus
  review_comment: string
  submitted_at: string | null
  reviewed_at: string | null
}

export interface MemberStat extends Progress {
  user_id: number
  username: string
  school: string
  role: Role
  status: MemberStatus
  review_comment: string
  submitted_at: string | null
  reviewed_at: string | null
  joined_at: string
}

export interface TaskStats {
  total: number
  unassigned: number
  done: number
  todo: number
  rework: number
  ann_count: number
  flagged: number
  done_today: number
  members: MemberStat[]
}

export interface Page<T> {
  total: number
  page: number
  page_size: number
  items: T[]
}
