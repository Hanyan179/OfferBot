import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Checkbox } from "@/components/ui/checkbox"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import React, { useState, useMemo } from 'react'
import { Play, X, Loader2 } from 'lucide-react'

/**
 * ActionCard — AI 生成的操作卡片。
 *
 * props 协议：
 * {
 *   card_type: "start_task" | "fetch_detail" | "deliver",
 *   title: string,
 *   description: string,
 *   fields: [{ id, label, type, value, required?, options? }],
 *   jobs: [{ id, title, company, salary, city, has_jd }],
 *   status: "pending" | "executing" | "completed" | "failed",
 *   result_message: string
 * }
 */
export default function ActionCard() {
  const fields = props.fields || []
  const jobs = props.jobs || []
  const status = props.status || "pending"

  const [values, setValues] = useState(() => {
    const init = {}
    fields.forEach(f => { init[f.id] = f.value ?? '' })
    return init
  })

  const [selectedJobIds, setSelectedJobIds] = useState(() => jobs.map(j => j.id))

  const allValid = useMemo(() => {
    const fieldsOk = fields.every(f => {
      if (!f.required) return true
      const v = values[f.id]
      return v !== undefined && v !== ''
    })
    if (jobs.length > 0 && selectedJobIds.length === 0) return false
    return fieldsOk
  }, [fields, values, jobs, selectedJobIds])

  const handleChange = (id, val) => setValues(v => ({ ...v, [id]: val }))

  const toggleJob = (jobId) => {
    setSelectedJobIds(prev =>
      prev.includes(jobId) ? prev.filter(id => id !== jobId) : [...prev, jobId]
    )
  }

  const toggleAll = () => {
    setSelectedJobIds(prev =>
      prev.length === jobs.length ? [] : jobs.map(j => j.id)
    )
  }

  const handleSubmit = () => {
    const payload = { card_type: props.card_type, tool_name: props.tool_name, params: fields.length > 0 ? values : (props.params || {}) }
    if (jobs.length > 0) payload.job_ids = selectedJobIds
    callAction({ name: "action_card_submit", payload })
    updateElement({ ...props, status: "executing" })
  }

  const handleCancel = () => {
    callAction({ name: "action_card_cancel", payload: { card_type: props.card_type } })
    deleteElement()
  }

  const isPending = status === "pending"
  const isExecuting = status === "executing"
  const isCompleted = status === "completed"
  const isFailed = status === "failed"

  const statusBadge = {
    pending:   { label: "待确认", variant: "outline" },
    executing: { label: "执行中", variant: "default" },
    completed: { label: "已完成", variant: "default" },
    failed:    { label: "失败",   variant: "destructive" },
  }[status] || { label: status, variant: "outline" }

  const renderField = (field) => {
    const val = values[field.id]
    const disabled = !isPending
    switch (field.type) {
      case 'select':
        return (
          <Select value={String(val)} onValueChange={v => handleChange(field.id, v)} disabled={disabled}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {(field.options || []).map(opt => {
                const v = typeof opt === 'object' ? opt.value : opt
                const l = typeof opt === 'object' ? opt.label : opt
                return <SelectItem key={v} value={v}>{l}</SelectItem>
              })}
            </SelectContent>
          </Select>
        )
      case 'switch':
        return <Switch checked={!!val} onCheckedChange={v => handleChange(field.id, v)} disabled={disabled} />
      case 'number':
        return <Input type="number" value={val} onChange={e => handleChange(field.id, Number(e.target.value))} disabled={disabled} className="w-24" />
      default:
        return <Input value={val} onChange={e => handleChange(field.id, e.target.value)} disabled={disabled} />
    }
  }

  return (
    <Card className="w-full max-w-2xl mt-2 mb-2">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle className="text-base">{props.title || "操作确认"}</CardTitle>
            <Badge variant="outline" className="text-xs font-normal">猎聘</Badge>
          </div>
          <Badge variant={statusBadge.variant}>{statusBadge.label}</Badge>
        </div>
        {props.description && <CardDescription>{props.description}</CardDescription>}
      </CardHeader>

      <CardContent className="space-y-3">
        {fields.map(field => (
          <div key={field.id} className="flex items-center gap-3">
            <Label className="w-24 text-right text-sm shrink-0">
              {field.label}{field.required && <span className="text-red-500 ml-0.5">*</span>}
            </Label>
            <div className="flex-1">{renderField(field)}</div>
          </div>
        ))}

        {jobs.length > 0 && (
          <div className="mt-2">
            <div className="flex items-center justify-between mb-2">
              <Label className="text-sm font-medium">选择岗位</Label>
              <Button variant="ghost" size="sm" onClick={toggleAll} disabled={!isPending}>
                {selectedJobIds.length === jobs.length ? "取消全选" : "全选"}
              </Button>
            </div>
            <ScrollArea className={jobs.length > 5 ? "h-48" : ""}>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-8"></TableHead>
                    <TableHead>岗位</TableHead>
                    <TableHead>公司</TableHead>
                    <TableHead>薪资</TableHead>
                    {props.card_type === "fetch_detail" && <TableHead>JD</TableHead>}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {jobs.map(job => (
                    <TableRow key={job.id}>
                      <TableCell>
                        <Checkbox
                          checked={selectedJobIds.includes(job.id)}
                          onCheckedChange={() => toggleJob(job.id)}
                          disabled={!isPending}
                        />
                      </TableCell>
                      <TableCell className="text-sm">{job.title}</TableCell>
                      <TableCell className="text-sm">{job.company}</TableCell>
                      <TableCell className="text-sm text-nowrap">{job.salary}</TableCell>
                      {props.card_type === "fetch_detail" && (
                        <TableCell>
                          <Badge variant={job.has_jd ? "default" : "outline"} className="text-xs">
                            {job.has_jd ? "有" : "无"}
                          </Badge>
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </ScrollArea>
            <p className="text-xs text-muted-foreground mt-1">已选 {selectedJobIds.length} / {jobs.length}</p>
          </div>
        )}

        {(isCompleted || isFailed) && props.result_message && (
          <div className={`text-sm p-2 rounded ${isCompleted ? 'bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-300' : 'bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300'}`}>
            {props.result_message}
          </div>
        )}
      </CardContent>

      {isPending && (
        <CardFooter className="flex justify-end gap-2 pt-0">
          <Button variant="outline" size="sm" onClick={handleCancel}>
            <X className="h-3.5 w-3.5 mr-1" /> 取消
          </Button>
          <Button size="sm" disabled={!allValid} onClick={handleSubmit}>
            <Play className="h-3.5 w-3.5 mr-1" /> 执行
          </Button>
        </CardFooter>
      )}

      {isExecuting && (
        <CardFooter className="pt-0">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> 执行中，可在任务面板查看进度...
          </div>
        </CardFooter>
      )}

      {/* 开源致谢 + 数据来源 */}
      <div className="px-6 pb-3">
        <Separator className="mb-2" />
        <p className="text-[11px] text-muted-foreground">
          数据采集由开源项目 <a href="https://github.com/loks666/get_jobs" target="_blank" rel="noopener" className="underline">get_jobs</a> 提供支持 · 数据来源：猎聘
        </p>
      </div>
    </Card>
  )
}
