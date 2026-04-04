import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Progress } from "@/components/ui/progress"

export default function InterviewTracker() {
  const funnel = props.funnel || []
  const interviews = props.interviews || []

  return (
    <Card className="w-full">
      <CardHeader className="pb-3">
        <CardTitle className="text-lg">🎯 面试追踪</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {funnel.length > 0 && (
          <div className="space-y-3">
            <p className="text-sm font-medium">面试漏斗</p>
            {funnel.map((stage, i) => (
              <div key={i} className="space-y-1">
                <div className="flex justify-between text-sm">
                  <span>{stage.name}</span>
                  <span className="text-muted-foreground">{stage.count} ({stage.rate})</span>
                </div>
                <Progress value={stage.percent} className="h-2" />
              </div>
            ))}
          </div>
        )}

        {interviews.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>岗位</TableHead>
                <TableHead>公司</TableHead>
                <TableHead>阶段</TableHead>
                <TableHead>更新时间</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {interviews.map((item, i) => (
                <TableRow key={i}>
                  <TableCell className="font-medium">{item.title}</TableCell>
                  <TableCell>{item.company}</TableCell>
                  <TableCell>
                    <Badge variant={
                      item.stage === "offer" ? "default" :
                      item.stage === "rejected" ? "destructive" : "secondary"
                    }>{item.stage_label}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground text-sm">{item.updated}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
