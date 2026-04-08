import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"

/**
 * JobList — 岗位列表展示组件。
 *
 * props:
 * {
 *   jobs: [{ seq, id, title, company, salary, city, url, has_jd }],
 *   total_matched: 45,
 *   showing: 20,
 * }
 */
export default function JobList() {
  const jobs = props.jobs || []
  const total = props.total_matched || jobs.length
  const showing = props.showing || jobs.length

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
          <CardDescription className="text-xs">
            共匹配 {total} 条，当前展示前 {showing} 条
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="pt-0">
        <ScrollArea className={jobs.length > 8 ? "h-80" : ""}>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8 text-center">#</TableHead>
                <TableHead>岗位</TableHead>
                <TableHead>公司</TableHead>
                <TableHead>薪资</TableHead>
                <TableHead>城市</TableHead>
                <TableHead className="w-10 text-center">JD</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobs.map((job) => (
                <TableRow key={job.id}>
                  <TableCell className="text-center text-xs text-muted-foreground">{job.seq}</TableCell>
                  <TableCell className="text-sm font-medium">
                    {job.url
                      ? <a href={job.url} target="_blank" rel="noopener" className="text-primary hover:underline">{job.title}</a>
                      : job.title}
                  </TableCell>
                  <TableCell className="text-sm">{job.company}</TableCell>
                  <TableCell className="text-sm text-nowrap">{job.salary}</TableCell>
                  <TableCell className="text-sm text-nowrap">{job.city}</TableCell>
                  <TableCell className="text-center">
                    {job.has_jd
                      ? <Badge variant="default" className="text-[10px] px-1.5 py-0">有</Badge>
                      : <Badge variant="outline" className="text-[10px] px-1.5 py-0">无</Badge>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </ScrollArea>
        <Separator className="mt-2 mb-1.5" />
        <p className="text-[11px] text-muted-foreground">
          数据来源：猎聘 · 对我说「第N个看看详情」或「帮我投递第N个」
        </p>
      </CardContent>
    </Card>
  )
}
