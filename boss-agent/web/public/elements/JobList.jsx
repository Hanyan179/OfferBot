import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Separator } from "@/components/ui/separator"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import React, { useState, useMemo } from 'react'
import { ChevronLeft, ChevronRight, ExternalLink, FileSearch } from 'lucide-react'

const PAGE_SIZE = 10

export default function JobList() {
  const jobs = props.jobs || []
  const total = props.total_matched || jobs.length
  const showing = props.showing || jobs.length
  const [page, setPage] = useState(0)

  const totalPages = Math.ceil(jobs.length / PAGE_SIZE)
  const pageJobs = useMemo(() => jobs.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE), [jobs, page])

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
              {showing === total ? `${total} 条` : `${showing}/${total} 条`}
            </Badge>
          </div>
        </div>
        {total > showing && (
          <CardDescription className="text-xs">共匹配 {total} 条，当前展示 {showing} 条</CardDescription>
        )}
      </CardHeader>
      <CardContent className="pt-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8 text-center">#</TableHead>
              <TableHead>岗位</TableHead>
              <TableHead>公司</TableHead>
              <TableHead>薪资</TableHead>
              <TableHead>城市</TableHead>
              <TableHead className="w-16 text-center">状态</TableHead>
              <TableHead className="w-16 text-center">操作</TableHead>
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
                <TableCell className="text-sm font-medium">
                  <a href={`/job/${job.id}`} target="_blank" rel="noopener" className="text-primary hover:underline">
                    {job.title}
                  </a>
                </TableCell>
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
            <span className="text-xs text-muted-foreground">第 {page + 1}/{totalPages} 页</span>
            <div className="flex gap-1">
              <Button variant="outline" size="sm" className="h-7 px-2" disabled={page === 0} onClick={() => setPage(p => p - 1)}>
                <ChevronLeft className="h-3.5 w-3.5" />
              </Button>
              <Button variant="outline" size="sm" className="h-7 px-2" disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)}>
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
