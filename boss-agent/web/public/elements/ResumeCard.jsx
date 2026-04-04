import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"

export default function ResumeCard() {
  const resume = props.resume || {}
  const suggestions = props.suggestions || []

  return (
    <Card className="w-full">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">📄 简历</CardTitle>
          <Badge variant="outline">{resume.name || "未上传"}</Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          你的简历数据。可以上传文件，也可以通过对话让 AI 帮你更新。
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {resume.tech_stack && (
          <div>
            <p className="text-sm font-medium mb-2">技术栈</p>
            <div className="flex flex-wrap gap-1.5">
              {resume.tech_stack.map((skill, i) => (
                <Badge key={i} variant="secondary" className="text-xs">{skill}</Badge>
              ))}
            </div>
          </div>
        )}

        {suggestions.length > 0 && (
          <>
            <Separator />
            <div>
              <p className="text-sm font-medium mb-2">优化建议</p>
              <ul className="space-y-1.5">
                {suggestions.map((s, i) => (
                  <li key={i} className="text-sm text-muted-foreground flex items-start gap-2">
                    <span>{s.icon}</span>
                    <span>{s.text}</span>
                  </li>
                ))}
              </ul>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
