import type { DiseaseGuideTopic } from "../../services/api";

interface DiseaseTopicMapProps {
  diseaseName: string;
  topics: DiseaseGuideTopic[];
  activeTopicId: string | null;
  onSelectTopic: (topicId: string) => void;
}

export default function DiseaseTopicMap({
  diseaseName,
  topics,
  activeTopicId,
  onSelectTopic,
}: DiseaseTopicMapProps) {
  return (
    <nav
      id="disease-guide-topic-directory"
      className="disease-topic-map"
      aria-label={`${diseaseName}知识主题`}
    >
      <div className="disease-topic-map-canvas">
        <div className="disease-topic-map-center">
          <span>疾病</span>
          <strong>{diseaseName}</strong>
        </div>
        <div className="disease-topic-map-topics">
          {topics.map((topic, index) => {
            const isActive = topic.id === activeTopicId;
            return (
              <button
                key={topic.id}
                type="button"
                className={`disease-topic-map-node${isActive ? " active" : ""}`}
                aria-label={`${topic.title}：${topic.question}`}
                aria-controls={`guide-topic-${topic.id}`}
                aria-current={isActive ? "location" : undefined}
                title={topic.question}
                onClick={() => onSelectTopic(topic.id)}
              >
                <span className="disease-topic-map-index" aria-hidden="true">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span>{topic.title}</span>
              </button>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
