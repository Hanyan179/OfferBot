import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Separator } from "@/components/ui/separator"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { Input } from "@/components/ui/input"
import React, { useState, useMemo } from 'react'
import { ChevronLeft, ChevronRight, ExternalLink, FileSearch, ArrowUpDown, ArrowUp, ArrowDown, Search, X } from 'lucide-react'

const PAGE_SIZE = 10

export default function JobList() {
  const jobs = props.jobs || []
  const total = props.total_matched || jobs.length
  const showing = props.showing || jobs.length
  const [page, setPage] = useState(0)
  const [keyword, setKeyword] = useState('')
  const [sortField, setSortField] = useState(null)
  const [sortOrder, setSortOrder] = useState('desc')

  const parseSalaryNum = (s) => {
    if (!s) return 0
    const m = String(s).match(/(\d+)/)
    return m ? parseInt(m[1]) : 0
  }

  const filtered = useMemo(() => {
    let list = jobs
    if (keyword.trim()) {
      const kw = keyword.trim().toLowerCase()
      list = list.filter(j =>
        (j.title || '').toLowerCase().includes(kw) ||
        (j.company || '').toLowerCase().includes(kw) ||
        (j.city || '').toLowerCase().includes(kw)
      )
    }
    if (sortField) {
      list = [...list].sort((a, b) => {
        let va, vb
        if (sortField === 'salary') {
          va = parseSalaryNum(a.salary)
          vb = parseSalaryNum(b.salary)
        }
        if (va == null) va = 0
        if (vb == null) vb = 0
        return sortOrder === 'asc' ? va - vb : vb - va
      })
    }
    return list
  }, [jobs, keyword, sortField, sortOrder])

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE)
  const safePage = Math.min(page, Math.max(totalPages - 1, 0))
  const pageJobs = useMemo(() => filtered.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE), [filtered, safePage])

  const toggleSort = (field) => {
    if (sortField === field) {
      setSortOrder(o => o === 'desc' ? 'asc' : 'desc')
    } else {
      setSortField(field)
      setSortOrder('desc')
    }
    setPage(0)
  }

  const SortIcon = ({ field }) => {
    if (sortField !== field) return <ArrowUpDown className="h-3 w-3 ml-0.5 opacity-30" />
    return sortOrder === 'asc'
      ? <ArrowUp className="h-3 w-3 ml-0.5 text-primary" />
      : <ArrowDown className="h-3 w-3 ml-0.5 text-primary" />
  }

  if (jobs.length === 0) {
    return (
      <Card className="w-full">
        <CardContent className="py-8 text-center text-muted-foreground text-sm">
          暂无匹配的岗位数据
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="w-full max-w-3xl mt-2 mb-2">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">📋 岗位列表</CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-xs">猎聘</Badge>
            <Badge variant="outline" className="text-xs">
              {filtered.length === total ? `${total} 条` : `${filtered.length}/${total} 条`}
            </Badge>
          </div>
        </div>
        {/* 搜索栏 */}
        <div className="flex items-center gap-2 mt-1.5">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              value={keyword}
              onChange={e => { setKeyword(e.target.value); setPage(0); }}
              placeholder="筛选岗位、公司、城市..."
              className="h-8 pl-8 text-xs"
            />
            {keyword && (
              <button onClick={() => { setKeyword(''); setPage(0); }}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8 text-center">#</TableHead>
              <TableHead>岗位</TableHead>
              <TableHead>公司</TableHead>
              <TableHead className="cursor-pointer select-none hover:text-primary" onClick={() => toggleSort('salary')}>
                <span className="inline-flex items-center">薪资<SortIcon field="salary" /></span>
              </TableHead>
              <TableHead>城市</TableHead>
              <TableHead className="w-16 text-center">状态</TableHead>
              <TableHead className="w-20 text-center">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pageJobs.map((job) => {
              let statusLabel, statusCls;
              if (job.has_rag) { statusLabel = "已图谱"; statusCls = "bg-purple-100 text-purple-700 dark:bg-purple-950 dark:text-purple-300"; }
              else if (job.has_analysis) { statusLabel = "已分析"; statusCls = "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300"; }
              else if (job.has_jd) { statusLabel = "有JD"; statusCls = "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300"; }
              else { statusLabel = "待爬取"; statusCls = "bg-muted text-muted-foreground"; }
              return (
              <TableRow key={job.id}>
                <TableCell className="text-center text-xs text-muted-foreground">{job.seq}</TableCell>
                <TableCell className="text-sm font-medium">{job.title}</TableCell>
                <TableCell className="text-sm">{job.company}</TableCell>
                <TableCell className="text-sm text-nowrap">{job.salary}</TableCell>
                <TableCell className="text-sm text-nowrap">{job.city}</TableCell>
                <TableCell className="text-center">
                  <Badge variant="outline" className={`text-[10px] px-1.5 py-0 ${statusCls}`}>{statusLabel}</Badge>
                </TableCell>
                <TableCell className="text-center">
                  <div className="flex items-center justify-center gap-1">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <a href={`/job/${job.id}`} target="_blank" rel="noopener"
                           className="inline-flex items-center justify-center h-6 w-6 rounded hover:bg-accent">
                          <FileSearch className="h-3.5 w-3.5 text-muted-foreground" />
                        </a>
                      </TooltipTrigger>
                      <TooltipContent>智能分析</TooltipContent>
                    </Tooltip>
                    {job.url && (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <a href={job.url} target="_blank" rel="noopener"
                             className="inline-flex items-center justify-center h-6 w-6 rounded hover:bg-accent">
                            <ExternalLink className="h-3.5 w-3.5 text-muted-foreground" />
                          </a>
                        </TooltipTrigger>
                        <TooltipContent>查看猎聘原文</TooltipContent>
                      </Tooltip>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            )})}
          </TableBody>
        </Table>

        {totalPages > 1 && (
          <div className="flex items-center justify-between mt-3">
            <span className="text-xs text-muted-foreground">第 {safePage + 1}/{totalPages} 页</span>
            <div className="flex gap-1">
              <Button variant="outline" size="sm" className="h-7 px-2" disabled={safePage === 0} onClick={() => setPage(p => p - 1)}>
                <ChevronLeft className="h-3.5 w-3.5" />
              </Button>
              <Button variant="outline" size="sm" className="h-7 px-2" disabled={safePage >= totalPages - 1} onClick={() => setPage(p => p + 1)}>
                <ChevronRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        )}

        <Separator className="mt-2 mb-1.5" />
        <p className="text-[11px] text-muted-foreground">
          数据来源：猎聘 · 对我说「第N个看看详情」或「帮我投递第N个」
        </p>
      </CardContent>
    </Card>
  )
}
