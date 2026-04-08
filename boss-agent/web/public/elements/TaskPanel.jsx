import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import React, { useEffect, useState } from 'react'
import { Loader2, CheckCircle, XCircle, Clock, Square } from 'lucide-react'

/**
 * TaskPanel — 任务进度面板，轮询 /api/tasks 或接收 props 更新。
 *
 * props:
 * {
 *   tasks: [
 *     {
 *       task_id: string,
 *       name: "爬取岗位列表",
 *       platform: "liepin",
 *       status: "running" | "completed" | "failed" | "timeout",
 *       progress_text: "32/100",
 *       elapsed_s: 45,
 *       started_at: "2026-04-08T11:00:00",
 *       finished_at: null,
 *     }
 *   ],
 *   poll_url: "/api/tasks"  // 可选，设置后自动轮询
 * }
 */
export default function TaskPanel() {
  const [tasks, setTasks] = useState(props.tasks || [])

  // 如果有 poll_url，自动轮询
  useEffect(() => {
    if (!props.poll_url) return
    const interval = setInterval(async () => {
      try {
        const res = await fetch(props.poll_url)
        const data = await res.json()
        if (data.tasks) {
          setTasks(data.tasks)
          updateElement({ ...props, tasks: data.tasks })
        }
      } catch (e) { /* ignore */ }
    }, 3000)
    return () => clearInterval(interval)
  }, [props.poll_url])

  // props 更新时同步
  useEffect(() => {
    if (props.tasks) setTasks(props.tasks)
  }, [props.tasks])

  const statusConfig = {
    running:   { icon: Loader2, label: "运行中", variant: "default", spin: true },
    completed: { icon: CheckCircle, label: "已完成", variant: "default", spin: false },
    failed:    { icon: XCircle, label: "失败", variant: "destructive", spin: false },
    timeout:   { icon: Clock, label: "超时", variant: "outline", spin: false },
  }

  const formatElapsed = (s) => {
    if (s < 60) return `${s}s`
    const m = Math.floor(s / 60)
    return `${m}m${s % 60}s`
  }

  // 从 progress_text 提取进度百分比（如 "32/100" → 32）
  const parseProgress = (text) => {
    if (!text) return 0
    const match = text.match(/^(\d+)\s*\/\s*(\d+)/)
    if (match) {
      const [, done, total] = match
      return total > 0 ? Math.round((done / total) * 100) : 0
    }
    return 0
  }

  const handleStop = (taskId, platform) => {
    callAction({
      name: "task_panel_stop",
      payload: { task_id: taskId, platform }
    })
  }

  if (tasks.length === 0) {
    return (
      <Card className="w-full max-w-sm">
        <CardContent className="py-6 text-center text-sm text-muted-foreground">
          暂无运行中的任务
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">📋 任务面板</CardTitle>
          <Badge variant="outline" className="text-xs">{tasks.filter(t => t.status === 'running').length} 运行中</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-0">
        <ScrollArea className={tasks.length > 4 ? "h-64" : ""}>
          {tasks.map((task, i) => {
            const cfg = statusConfig[task.status] || statusConfig.running
            const Icon = cfg.icon
            const pct = parseProgress(task.progress_text)

            return (
              <div key={task.task_id}>
                {i > 0 && <Separator className="my-2" />}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <Icon className={`h-3.5 w-3.5 ${cfg.spin ? 'animate-spin' : ''} ${task.status === 'completed' ? 'text-green-600' : task.status === 'failed' ? 'text-red-600' : ''}`} />
                      <span className="text-sm font-medium">{task.name}</span>
                    </div>
                    {task.status === 'running' && (
                      <Button variant="ghost" size="sm" className="h-6 px-1.5" onClick={() => handleStop(task.task_id, task.platform)}>
                        <Square className="h-3 w-3" />
                      </Button>
                    )}
                  </div>

                  {task.status === 'running' && pct > 0 && (
                    <Progress value={pct} className="h-1.5" />
                  )}

                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>{task.progress_text || task.status}</span>
                    <span>{formatElapsed(task.elapsed_s || 0)}</span>
                  </div>
                </div>
              </div>
            )
          })}
        </ScrollArea>
      </CardContent>
    </Card>
  )
}
