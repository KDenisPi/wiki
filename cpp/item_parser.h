/**
 * @file item_parser.h
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-08-13
 *
 * @copyright Copyright (c) 2025
 *
 */

#ifndef WIKI_ITEM_PARSER_H_
#define WIKI_ITEM_PARSER_H_

#include <memory>
#include "rapidjson/document.h"

namespace wiki {

class ItemParser{
public:
    ItemParser() {
    }

    virtual ~ItemParser() {
        release();
    }

    /**
     * @brief
     *
     * @param buff
     * @return true
     * @return false
     */
    bool load(const char* buff){
        ptr_doc = std::make_shared<rapidjson::Document>();

        ptr_doc->Parse(buff);
        if(ptr_doc->HasParseError()){
            auto err = ptr_doc->GetParseError();
            std::cout << " Parse error: " << std::to_string(err) << " Offset: " << ptr_doc->GetErrorOffset() << std::endl;

            release();
            return false;
        }

        return true;
    }

    /**
     * @brief
     *
     */
    void release(){
        if(ptr_doc){
            ptr_doc.reset();
        }
    }

    virtual void process(){}

    /**
     * @brief
     *
     * @return const std::shared_ptr<rapidjson::Document>
     */
    const std::shared_ptr<rapidjson::Document> get() {
        return ptr_doc;
    }

private:
    std::shared_ptr<rapidjson::Document> ptr_doc;

};

} //namespace
#endif