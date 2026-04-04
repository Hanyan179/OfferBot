import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

export default function JobList() {
  const jobs = props.jobs || []

  if (jobs.length === 0) {
    return (
      <Card className="w-full">
        <CardContent className="py-8 text-center text-muted-foreground">
          暂无岗位数据，试试对我说「帮我搜索上海 AI 岗位」
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="w-full">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">📋 岗位数据</CardTitle>
          <Badge variant="outline">{jobs.length} 个岗位</Badge>
        </div>
        <p className="text-sm text-muted-foreground">本地缓存的岗位数据，供 AI 分析使用</p>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>岗位</TableHead>
              <TableHead>公司</TableHead>
              <TableHead>薪资</TableHead>
              <TableHead>城市</TableHead>
              <TableHead>匹配度</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {jobs.map((job, i) => (
              <TableRow key={i}>
                <TableCell className="font-medium">
                  {job.url ? <a href={job.url} target="_blank" rel="noopener" className="text-primary hover:underline">{job.title}</a> : job.title}
                </TableCell>
                <TableCell>{job.company}</TableCell>
                <TableCell>{job.salary}</TableCell>
                <TableCell>{job.city}</TableCell>
                <TableCell>
                  <Badge variant={job.score >= 80 ? "default" : "secondary"}>{job.score}%</Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
